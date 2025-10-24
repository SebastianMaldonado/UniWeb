import re
from typing import Optional
import json
from base64 import b64decode

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.contrib.auth.hashers import make_password, check_password
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils.text import get_valid_filename
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

from .models import User, Post, Comment, Notification, Message


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _get_user_by_username(username: str) -> Optional[User]:
	try:
		return User.nodes.get(username=username)
	except User.DoesNotExist:
		return None


def _get_user_by_email(email: str) -> Optional[User]:
	try:
		return User.nodes.get(email=email)
	except User.DoesNotExist:
		return None


def _get_logged_in_username(request: HttpRequest) -> Optional[str]:
	return request.session.get("username")


def root(request: HttpRequest) -> HttpResponse:
	# If logged in, go to home; else go to login
	if _get_logged_in_username(request):
		return redirect("home")
	return redirect("login")


def logout_view(request: HttpRequest) -> HttpResponse:
	"""Log out the current user by clearing the session and redirecting to login."""
	try:
		request.session.flush()
	except Exception:
		request.session.clear()
	return redirect("login")


def home(request: HttpRequest) -> HttpResponse:
	if not _get_logged_in_username(request):
		return redirect("login")
	# Build feed: followed users' posts -> interest-matching -> latest
	username = _get_logged_in_username(request)
	user = _get_user_by_username(username)
	if not user:
		return redirect("login")

	# Collect all posts (simple approach) sorted by created_at desc
	try:
		all_posts = list(Post.nodes.all())
	except Exception:
		all_posts = []
	all_posts.sort(key=lambda p: getattr(p, 'created_at', None) or 0, reverse=True)

	# Following usernames
	try:
		following_users = list(user.following.all())
	except Exception:
		following_users = []
	following_usernames = {u.username for u in following_users}

	# Interests: hashtags used by this user's own posts
	my_posts = [p for p in all_posts if p.author_username == username]
	my_interests = set()
	for p in my_posts:
		for tag in (p.hashtags or []):
			my_interests.add(tag.lower())

	feed_following = [p for p in all_posts if p.author_username in following_usernames]
	picked = set(id(p) for p in feed_following)
	feed_interests = [p for p in all_posts if id(p) not in picked and any((tag.lower() in my_interests) for tag in (p.hashtags or []))]
	picked.update(id(p) for p in feed_interests)
	feed_latest = [p for p in all_posts if id(p) not in picked]

	feed = feed_following + feed_interests + feed_latest
	# Do not show my own posts in home feed
	feed = [p for p in feed if p.author_username != username]
	# limit initial feed
	feed = feed[:20]

	posts_ctx = [_serialize_post_card(p, following_usernames=following_usernames, me_username=username) for p in feed]
	return render(request, "home.html", {"posts": posts_ctx})


def login_view(request: HttpRequest) -> HttpResponse:
	error = None
	if request.method == "POST":
		username = request.POST.get("username", "").strip()
		password = request.POST.get("password", "")

		if not username or not password:
			error = "Ingresa usuario y contraseña."
		else:
			user = _get_user_by_username(username)
			if user and check_password(password, user.password_hash):
				# Set session and redirect
				request.session["user_uid"] = user.uid
				request.session["username"] = user.username
				return redirect("home")
			else:
				error = "Usuario o contraseña incorrectos."

	return render(request, "login.html", {"error": error})


def register_view(request: HttpRequest) -> HttpResponse:
	error = None
	if request.method == "POST":
		username = request.POST.get("username", "").strip()
		email = request.POST.get("email", "").strip()
		password = request.POST.get("password", "")
		password2 = request.POST.get("password2", "")

		# Validate username
		if not USERNAME_RE.match(username):
			error = "El nombre de usuario solo puede contener letras, números y _."
		else:
			# Validate email
			try:
				validate_email(email)
			except ValidationError:
				error = "Correo electrónico inválido."

		if not error and password != password2:
			error = "Las contraseñas no coinciden."

		if not error:
			# Check uniqueness
			if _get_user_by_username(username):
				error = "El nombre de usuario ya existe."
			elif _get_user_by_email(email):
				error = "El correo ya está registrado."

		if not error:
			# Create user
			password_hash = make_password(password)
			user = User(username=username, email=email, password_hash=password_hash)
			user.save()
			# Login: set session
			request.session["user_uid"] = user.uid
			request.session["username"] = user.username
			return redirect("profile_edit")

	return render(request, "register.html", {"error": error})


def notifications_view(request: HttpRequest) -> HttpResponse:
	if not _get_logged_in_username(request):
		return redirect("login")
	return render(request, "notifications.html")


def profile_edit_view(request: HttpRequest) -> HttpResponse:
	if not _get_logged_in_username(request):
		return redirect("login")

	user = _get_user_by_username(_get_logged_in_username(request))
	if not user:
		return redirect("login")

	error = None
	genders = ["masculino", "femenino", "otro"]

	if request.method == "POST":
		# Files (optional)
		profile_image_file = request.FILES.get("profile_image")
		cover_image_file = request.FILES.get("cover_image")
		profile_image_cropped = request.POST.get("profile_image_cropped", "").strip()
		cover_image_cropped = request.POST.get("cover_image_cropped", "").strip()
		gender = request.POST.get("gender", "").strip().lower() or None
		bio = (request.POST.get("bio", "") or "").strip()
		if len(bio) > 200:
			bio = bio[:200]
		birthdate = request.POST.get("birthdate", "").strip()
		birthdate_dt = None

		if not error and gender and gender not in genders:
			error = "Género inválido."

		# Validate birthdate as YYYY-MM-DD and convert to datetime.date
		if not error and birthdate:
			try:
				from datetime import date
				parts = [int(p) for p in birthdate.split("-")]
				if len(parts) == 3:
					birthdate_dt = date(parts[0], parts[1], parts[2])
				else:
					raise ValueError
			except Exception:
				error = "Fecha de nacimiento inválida."

		if not error:
			# Save images if provided (prefer cropped data URLs over raw files)
			def _save_image(file_obj, kind: str) -> str:
				# kind in {"profile", "cover"}
				base = f"users/{user.username}/{kind}/"
				name = get_valid_filename(file_obj.name)
				path = default_storage.save(base + name, file_obj)
				# Return URL for template usage
				return settings.MEDIA_URL + path if not default_storage.url(path).startswith('http') else default_storage.url(path)

			def _save_data_url(data_url: str, kind: str) -> Optional[str]:
				# Expect data:image/png;base64,.... or image/jpeg
				m = re.match(r"^data:image/(png|jpeg);base64,(.+)$", data_url)
				if not m:
					return None
				ext = 'png' if m.group(1) == 'png' else 'jpg'
				b64data = m.group(2)
				content = ContentFile(b64decode(b64data))
				base = f"users/{user.username}/{kind}/"
				name = f"{kind}_cropped.{ext}"
				path = default_storage.save(base + name, content)
				return settings.MEDIA_URL + path if not default_storage.url(path).startswith('http') else default_storage.url(path)

			if profile_image_cropped:
				saved = _save_data_url(profile_image_cropped, "profile")
				if saved:
					user.profile_image_url = saved
			elif profile_image_file:
				user.profile_image_url = _save_image(profile_image_file, "profile")
			if cover_image_cropped:
				saved = _save_data_url(cover_image_cropped, "cover")
				if saved:
					user.cover_image_url = saved
			elif cover_image_file:
				user.cover_image_url = _save_image(cover_image_file, "cover")

			# Persist other fields
			user.gender = gender
			user.bio = bio or None
			user.birthdate = birthdate_dt if birthdate else None
			user.save()
			return redirect("home")

	context = {
		"genders": genders,
		"profile_image_url": getattr(user, "profile_image_url", "") or "",
		"cover_image_url": getattr(user, "cover_image_url", "") or "",
		"gender": getattr(user, "gender", "") or "",
		"bio": getattr(user, "bio", "") or "",
		"birthdate": getattr(user, "birthdate", "") or "",
		"error": error,
	}
	return render(request, "profile_edit.html", context)


def _login_required(request: HttpRequest) -> Optional[HttpResponse]:
	if not _get_logged_in_username(request):
		return redirect("login")
	return None


def search_view(request: HttpRequest) -> HttpResponse:
	maybe = _login_required(request)
	if maybe: return maybe
	return render(request, "search.html")


def friends_view(request: HttpRequest) -> HttpResponse:
	maybe = _login_required(request)
	if maybe: return maybe
	return render(request, "friends.html")


def new_post_view(request: HttpRequest) -> HttpResponse:
	maybe = _login_required(request)
	if maybe: return maybe
	me = _get_user_by_username(_get_logged_in_username(request))
	if not me:
		return redirect("login")

	error = None
	ok = False

	if request.method == "POST":
		title = (request.POST.get("title", "") or "").strip()
		description = (request.POST.get("description", "") or "").strip()
		# clamp description
		if len(description) > 500:
			description = description[:500]

		# arrays
		links = request.POST.getlist("links[]") or []
		hashtags = request.POST.getlist("hashtags[]") or []
		images_b64 = request.POST.getlist("images[]") or []

		# basic validation
		if not title:
			error = "El título es obligatorio."
		elif not hashtags:
			error = "Agrega al menos un tema (#hashtag)."

		def _save_data_url(data_url: str, base_folder: str, name: str) -> Optional[str]:
			m = re.match(r"^data:image/(png|jpeg);base64,(.+)$", data_url)
			if not m:
				return None
			ext = 'png' if m.group(1) == 'png' else 'jpg'
			b64data = m.group(2)
			content = ContentFile(b64decode(b64data))
			path = default_storage.save(f"{base_folder}/{name}.{ext}", content)
			url = default_storage.url(path)
			# ensure MEDIA_URL when storage returns relative
			return settings.MEDIA_URL + path if not url.startswith('http') else url

		if not error:
			# Persist images
			from datetime import datetime
			base_folder = f"users/{me.username}/posts/{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
			image_urls = []
			for idx, img in enumerate(images_b64):
				saved = _save_data_url(img, base_folder, f"img_{idx}")
				if saved:
					image_urls.append(saved)

			# Normalize hashtags to lower without leading '#'
			norm_tags = []
			for t in hashtags:
				t = (t or '').strip()
				if not t:
					continue
				if t.startswith('#'):
					t = t[1:]
				if t:
					norm_tags.append(t.lower())

			post = Post(
				title=title,
				description=description or None,
				images=image_urls,
				links=[(l or '').strip() for l in links if (l or '').strip()],
				hashtags=norm_tags,
				author_username=me.username,
				author_uid=me.uid,
			).save()
			# Connect author relationship
			try:
				post.author.connect(me)
			except Exception:
				pass
			ok = True
			return redirect("home")

	return render(request, "new_post.html", {"error": error, "ok": ok})


def chat_view(request: HttpRequest) -> HttpResponse:
	maybe = _login_required(request)
	if maybe: return maybe
	me_username = _get_logged_in_username(request)
	me = _get_user_by_username(me_username)
	# Build following list (left sidebar)
	def _ago(dt) -> str:
		try:
			from datetime import datetime, timezone
			now = datetime.now(timezone.utc) if getattr(dt, 'tzinfo', None) else datetime.utcnow()
			diff = now - dt
			seconds = int(diff.total_seconds())
			minutes = seconds // 60
			hours = minutes // 60
			days = hours // 24
			if days > 0:
				return f"{days}d"
			if hours > 0:
				return f"{hours}h"
			return f"{max(1, minutes)}m"
		except Exception:
			return ""

	try:
		following_users = list(me.following.all()) if me else []
	except Exception:
		following_users = []
	following_ctx = []
	for u in following_users:
		unread_count = 0
		last_ago = ""
		try:
			unread = list(Message.nodes.filter(sender_username=u.username, receiver_username=me_username, seen=False))
			unread_count = len(unread)
			if unread:
				# latest by created_at
				unread.sort(key=lambda m: getattr(m, 'created_at', None) or 0, reverse=True)
				last_dt = getattr(unread[0], 'created_at', None)
				if last_dt:
					last_ago = _ago(last_dt)
		except Exception:
			pass
		following_ctx.append({
			"username": u.username,
			"profile_image_url": getattr(u, "profile_image_url", "") or "",
			"unread_count": unread_count,
			"last_unread_ago": last_ago,
		})

	# Also include users I've chatted with before (even if not following)
	try:
		msgs_out = list(Message.nodes.filter(sender_username=me_username))
	except Exception:
		msgs_out = []
	try:
		msgs_in = list(Message.nodes.filter(receiver_username=me_username))
	except Exception:
		msgs_in = []
	partners = set()
	for m in msgs_out:
		other = getattr(m, 'receiver_username', None)
		if other and other != me_username:
			partners.add(other)
	for m in msgs_in:
		other = getattr(m, 'sender_username', None)
		if other and other != me_username:
			partners.add(other)
	# Index existing following entries to avoid duplicates
	existing = {d["username"] for d in following_ctx}
	for uname in partners:
		if uname in existing:
			continue
		u = _get_user_by_username(uname)
		unread_count = 0
		last_ago = ""
		try:
			unread = list(Message.nodes.filter(sender_username=uname, receiver_username=me_username, seen=False))
			unread_count = len(unread)
			if unread:
				unread.sort(key=lambda m: getattr(m, 'created_at', None) or 0, reverse=True)
				last_dt = getattr(unread[0], 'created_at', None)
				if last_dt:
					last_ago = _ago(last_dt)
		except Exception:
			pass
		following_ctx.append({
			"username": uname,
			"profile_image_url": getattr(u, "profile_image_url", "") if u else "",
			"unread_count": unread_count,
			"last_unread_ago": last_ago,
		})
	# Optional preselected user via query param
	sel_username = (request.GET.get('user', '') or '').strip()
	sel_user = _get_user_by_username(sel_username) if sel_username else None
	sel_ctx = None
	if sel_user:
		sel_ctx = {
			"username": sel_user.username,
			"profile_image_url": getattr(sel_user, "profile_image_url", "") or "",
		}
	return render(request, "chat.html", {
		"following": following_ctx,
		"following_json": json.dumps(following_ctx),
		"selected": sel_ctx,
		"selected_username": sel_ctx["username"] if sel_ctx else "",
	})


def _serialize_message(m: Message, me_username: str) -> dict:
	return {
		"uid": m.uid,
		"sender_username": m.sender_username,
		"receiver_username": m.receiver_username,
		"text": m.text or "",
		"image_url": m.image_url or "",
		"created_at": m.created_at.isoformat() if getattr(m, 'created_at', None) else '',
		"is_me": (m.sender_username == me_username),
	}


def chat_messages(request: HttpRequest, username: str) -> HttpResponse:
	maybe = _login_required(request)
	if maybe:
		return maybe
	me_username = _get_logged_in_username(request)
	if not me_username:
		return HttpResponse(status=403)
	# Ensure target exists
	target = _get_user_by_username(username)
	if not target:
		return HttpResponse(status=404)
	# Fetch both directions and merge
	try:
		a = list(Message.nodes.filter(sender_username=me_username, receiver_username=username))
	except Exception:
		a = []
	try:
		b = list(Message.nodes.filter(sender_username=username, receiver_username=me_username))
	except Exception:
		b = []
	all_msgs = a + b
	all_msgs.sort(key=lambda m: getattr(m, 'created_at', None) or 0)
	# Mark messages to me as seen
	for m in all_msgs:
		try:
			if getattr(m, 'receiver_username', None) == me_username and not getattr(m, 'seen', False):
				m.seen = True
				m.save()
		except Exception:
			pass
	return HttpResponse(json.dumps({
		"messages": [_serialize_message(m, me_username) for m in all_msgs]
	}), content_type="application/json")


@csrf_exempt
def chat_send(request: HttpRequest, username: str) -> HttpResponse:
	maybe = _login_required(request)
	if maybe:
		return maybe
	if request.method != 'POST':
		return HttpResponse(status=405)
	me_username = _get_logged_in_username(request)
	me = _get_user_by_username(me_username)
	if not me:
		return HttpResponse(status=403)
	target = _get_user_by_username(username)
	if not target:
		return HttpResponse(status=404)
	text = (request.POST.get('text', '') or '').strip()
	if len(text) > 2000:
		text = text[:2000]
	image_url = ''
	# Optional image upload
	if 'image' in request.FILES:
		try:
			img = request.FILES['image']
			name = f"chat/{me_username}_to_{username}_" + get_valid_filename(img.name)
			saved = default_storage.save(name, img)
			image_url = settings.MEDIA_URL + saved
		except Exception:
			image_url = ''
	if not text and not image_url:
		return HttpResponse(json.dumps({"error": "Mensaje o imagen requerido"}), content_type="application/json", status=400)
	m = Message(
		sender_username=me.username,
		sender_uid=me.uid,
		receiver_username=target.username,
		receiver_uid=target.uid,
		text=text or None,
		image_url=image_url or None,
	).save()
	return HttpResponse(json.dumps({"message": _serialize_message(m, me_username)}), content_type="application/json")


def profile_view(request: HttpRequest) -> HttpResponse:
	maybe = _login_required(request)
	if maybe: return maybe
	# Load current user profile
	username = _get_logged_in_username(request)
	user = _get_user_by_username(username) if username else None
	if not user:
		return redirect("login")

	# Prepare followers/following lists and counts
	try:
		followers = list(user.followers.all())
	except Exception:
		followers = []
	try:
		following = list(user.following.all())
	except Exception:
		following = []

	followers_ctx = [
		{
			"username": u.username,
			"profile_image_url": getattr(u, "profile_image_url", "") or "",
		}
		for u in followers
	]
	following_ctx = [
		{
			"username": u.username,
			"profile_image_url": getattr(u, "profile_image_url", "") or "",
		}
		for u in following
	]

	# User's own posts
	try:
		user_posts = [p for p in Post.nodes.all() if p.author_username == user.username]
	except Exception:
		user_posts = []
	user_posts.sort(key=lambda p: getattr(p, 'created_at', None) or 0, reverse=True)

	# Following set for serializer
	try:
		following_set = set(u.username for u in following)
	except Exception:
		following_set = set()

	context = {
		"username": user.username,
		"bio": getattr(user, "bio", "") or "",
		"profile_image_url": getattr(user, "profile_image_url", "") or "",
		"cover_image_url": getattr(user, "cover_image_url", "") or "",
		"followers_count": len(followers_ctx),
		"following_count": len(following_ctx),
		"followers": followers_ctx,
		"following": following_ctx,
		"followers_json": json.dumps(followers_ctx),
		"following_json": json.dumps(following_ctx),
		"posts": [_serialize_post_card(p, following_usernames=following_set, me_username=user.username) for p in user_posts],
			"is_self": True,
			"is_following": False,
	}
	return render(request, "profile.html", context)


def user_profile_view(request: HttpRequest, username: str) -> HttpResponse:
	"""Public profile page for any user by username."""
	maybe = _login_required(request)
	if maybe:
		return maybe

	# Load target user
	user = _get_user_by_username(username)
	if not user:
		return HttpResponse("Usuario no encontrado", status=404)
	me_username = _get_logged_in_username(request)
	me = _get_user_by_username(me_username) if me_username else None

	# Prepare followers/following
	try:
		followers = list(user.followers.all())
	except Exception:
		followers = []
	try:
		following = list(user.following.all())
	except Exception:
		following = []

	followers_ctx = [
		{
			"username": u.username,
			"profile_image_url": getattr(u, "profile_image_url", "") or "",
		}
		for u in followers
	]
	following_ctx = [
		{
			"username": u.username,
			"profile_image_url": getattr(u, "profile_image_url", "") or "",
		}
		for u in following
	]

	# Compute following state and mutual friends
	try:
		me_following = set(u.username for u in (list(me.following.all()) if me else []))
	except Exception:
		me_following = set()
	is_self = bool(me_username == user.username)
	is_following = (user.username in me_following) if me else False
	# mutual friends: users both follow
	try:
		target_following = set(u.username for u in following)
	except Exception:
		target_following = set()
	mutual_usernames = list(me_following.intersection(target_following)) if me else []

	# User's posts
	try:
		user_posts = [p for p in Post.nodes.all() if p.author_username == user.username]
	except Exception:
		user_posts = []
	user_posts.sort(key=lambda p: getattr(p, 'created_at', None) or 0, reverse=True)

	context = {
		"username": user.username,
		"bio": getattr(user, "bio", "") or "",
		"profile_image_url": getattr(user, "profile_image_url", "") or "",
		"cover_image_url": getattr(user, "cover_image_url", "") or "",
		"followers_count": len(followers_ctx),
		"following_count": len(following_ctx),
		"followers": followers_ctx,
		"following": following_ctx,
		"followers_json": json.dumps(followers_ctx),
		"following_json": json.dumps(following_ctx),
		"posts": [_serialize_post_card(p, following_usernames=me_following, me_username=me_username) for p in user_posts],
		"is_self": is_self,
		"is_following": is_following,
		"mutual_count": len(mutual_usernames),
	}
	return render(request, "profile.html", context)


def _serialize_post_card(p: Post, following_usernames: set | None = None, me_username: str | None = None) -> dict:
	# Load author details for avatar
	author = _get_user_by_username(p.author_username)
	return {
		"uid": p.uid,
		"title": p.title,
		"author_username": p.author_username,
		"author_avatar": getattr(author, "profile_image_url", "") or "",
		"images": list(p.images or []),
		"description": p.description or "",
		"links": list(p.links or []),
		"hashtags": list(p.hashtags or []),
		"likes_count": _safe_rel_count(p, 'liked_by'),
		"comments_count": _safe_rel_count(p, 'comments'),
		"author_followed": bool(following_usernames and (p.author_username in following_usernames)),
		"is_author_me": bool(me_username and (p.author_username == me_username)),
	}


def _safe_rel_count(obj, rel_name: str) -> int:
	try:
		rel = getattr(obj, rel_name)
		return len(list(rel.all()))
	except Exception:
		return 0


@csrf_exempt
def post_like_toggle(request: HttpRequest, post_uid: str) -> HttpResponse:
	maybe = _login_required(request)
	if maybe:
		return maybe
	if request.method != "POST":
		return HttpResponse(status=405)
	user = _get_user_by_username(_get_logged_in_username(request))
	if not user:
		return HttpResponse(status=403)
	try:
		post = Post.nodes.get(uid=post_uid)
	except Post.DoesNotExist:
		return HttpResponse(status=404)

	# Toggle like
	try:
		liked_users = list(post.liked_by.all())
	except Exception:
		liked_users = []
	if any(u.username == user.username for u in liked_users):
		# unlike: neomodel relationship managers support disconnect
		post.liked_by.disconnect(user)
		liked = False
	else:
		post.liked_by.connect(user)
		liked = True
		# create notification to post author (if not self)
		if post.author_username != user.username:
			try:
				Notification(
					to_username=post.author_username,
					to_uid=post.author_uid,
					from_username=user.username,
					from_uid=user.uid,
					type='like_post',
					target_uid=post.uid,
					element_type='post',
				).save()
			except Exception:
				pass
	return HttpResponse(json.dumps({"liked": liked, "likes": _safe_rel_count(post, 'liked_by')}), content_type="application/json")


def post_comments_json(request: HttpRequest, post_uid: str) -> HttpResponse:
	maybe = _login_required(request)
	if maybe:
		return maybe
	try:
		post = Post.nodes.get(uid=post_uid)
	except Post.DoesNotExist:
		return HttpResponse(status=404)

	# Build nested comments tree
	def serialize_comment(c: Comment) -> dict:
		try:
			replies = list(c.replies.all())
		except Exception:
			replies = []
		# enrich with avatar and timestamp
		try:
			user = _get_user_by_username(c.author_username)
			avatar = user.profile_image_url if user and getattr(user, 'profile_image_url', None) else ''
		except Exception:
			avatar = ''
		return {
			"uid": c.uid,
			"author_username": c.author_username,
			"text": c.text,
			"likes": _safe_rel_count(c, 'liked_by'),
			"author_avatar": avatar,
			"created_at": (c.created_at.isoformat() if getattr(c, 'created_at', None) else ''),
			"replies": [serialize_comment(rc) for rc in replies],
		}

	comments = []
	try:
		top = list(post.comments.all())
	except Exception:
		top = []
	for c in top:
		comments.append(serialize_comment(c))
	return HttpResponse(json.dumps({"comments": comments}), content_type="application/json")


@csrf_exempt
def post_add_comment(request: HttpRequest, post_uid: str) -> HttpResponse:
	maybe = _login_required(request)
	if maybe:
		return maybe
	if request.method != "POST":
		return HttpResponse(status=405)
	try:
		post = Post.nodes.get(uid=post_uid)
	except Post.DoesNotExist:
		return HttpResponse(status=404)
	me = _get_user_by_username(_get_logged_in_username(request))
	if not me:
		return HttpResponse(status=403)
	text = (request.POST.get('text', '') or '').strip()
	if not text:
		return HttpResponse(json.dumps({"error": "Texto requerido"}), content_type="application/json", status=400)
	if len(text) > 500:
		text = text[:500]
	c = Comment(text=text, author_username=me.username, author_uid=me.uid).save()
	post.comments.connect(c)
	# notify post author if different
	if post.author_username != me.username:
		try:
			Notification(
				to_username=post.author_username,
				to_uid=post.author_uid,
				from_username=me.username,
				from_uid=me.uid,
				type='comment_post',
				target_uid=c.uid,
				element_type='comment',
			).save()
		except Exception:
			pass
	return HttpResponse(json.dumps({"ok": True}), content_type="application/json")


@csrf_exempt
def post_add_reply(request: HttpRequest, post_uid: str, comment_uid: str) -> HttpResponse:
	maybe = _login_required(request)
	if maybe:
		return maybe
	if request.method != "POST":
		return HttpResponse(status=405)
	# Ensure post exists (optional integrity)
	try:
		_ = Post.nodes.get(uid=post_uid)
	except Post.DoesNotExist:
		return HttpResponse(status=404)
	# Find parent comment
	try:
		parent = Comment.nodes.get(uid=comment_uid)
	except Comment.DoesNotExist:
		return HttpResponse(status=404)
	me = _get_user_by_username(_get_logged_in_username(request))
	if not me:
		return HttpResponse(status=403)
	text = (request.POST.get('text', '') or '').strip()
	if not text:
		return HttpResponse(json.dumps({"error": "Texto requerido"}), content_type="application/json", status=400)
	if len(text) > 500:
		text = text[:500]
	rep = Comment(text=text, author_username=me.username, author_uid=me.uid).save()
	parent.replies.connect(rep)
	# notify parent comment author if different
	try:
		target_user = parent.author_username
	except Exception:
		target_user = None
	if target_user and target_user != me.username:
		try:
			Notification(
				to_username=parent.author_username,
				to_uid=parent.author_uid,
				from_username=me.username,
				from_uid=me.uid,
				type='reply_comment',
				target_uid=rep.uid,
				element_type='comment',
			).save()
		except Exception:
			pass
	return HttpResponse(json.dumps({"ok": True}), content_type="application/json")


@csrf_exempt
def comment_like_toggle(request: HttpRequest, comment_uid: str) -> HttpResponse:
	maybe = _login_required(request)
	if maybe:
		return maybe
	if request.method != 'POST':
		return HttpResponse(status=405)
	try:
		comment = Comment.nodes.get(uid=comment_uid)
	except Comment.DoesNotExist:
		return HttpResponse(status=404)
	user = _get_user_by_username(_get_logged_in_username(request))
	if not user:
		return HttpResponse(status=403)
	# toggle like
	try:
		liked_users = list(comment.liked_by.all())
	except Exception:
		liked_users = []
	if any(u.username == user.username for u in liked_users):
		comment.liked_by.disconnect(user)
		liked = False
	else:
		comment.liked_by.connect(user)
		liked = True
		# notification to comment author if not self
		if comment.author_username != user.username:
			try:
				Notification(
					to_username=comment.author_username,
					to_uid=comment.author_uid,
					from_username=user.username,
					from_uid=user.uid,
					type='like_comment',
					target_uid=comment.uid,
					element_type='comment',
				).save()
			except Exception:
				pass
	return HttpResponse(json.dumps({"liked": liked, "likes": _safe_rel_count(comment, 'liked_by')}), content_type="application/json")


@csrf_exempt
def follow_toggle(request: HttpRequest, username: str) -> HttpResponse:
	maybe = _login_required(request)
	if maybe:
		return maybe
	if request.method != 'POST':
		return HttpResponse(status=405)
	me = _get_user_by_username(_get_logged_in_username(request))
	target = _get_user_by_username(username)
	if not me or not target or me.username == target.username:
		return HttpResponse(status=400)
	try:
		current = set(u.username for u in me.following.all())
	except Exception:
		current = set()
	if username in current:
		me.following.disconnect(target)
		following = False
	else:
		me.following.connect(target)
		following = True
		# notification to the target when newly followed
		try:
			Notification(
				to_username=target.username,
				to_uid=target.uid,
				from_username=me.username,
				from_uid=me.uid,
				type='follow',
				target_uid=me.username,
				element_type='account',
			).save()
		except Exception:
			pass
	return HttpResponse(json.dumps({"following": following}), content_type="application/json")


def _resolve_post_uid_for_comment(comment_uid: str) -> Optional[str]:
	try:
		c = Comment.nodes.get(uid=comment_uid)
		# traverse back to post
		posts = list(c.on_post.all())
		if posts:
			return posts[0].uid
		# if it's a reply, find root post via parent chain
		parents = list(c.on_comment.all())
		while parents:
			parent = parents[0]
			posts = list(parent.on_post.all())
			if posts:
				return posts[0].uid
			parents = list(parent.on_comment.all())
	except Exception:
		return None
	return None


def notifications_view(request: HttpRequest) -> HttpResponse:
	maybe = _login_required(request)
	if maybe:
		return maybe
	me_username = _get_logged_in_username(request)
	me = _get_user_by_username(me_username)
	if not me:
		return redirect('login')
	# fetch notifications for me
	try:
		all_notifs = list(Notification.nodes.filter(to_username=me_username))
	except Exception:
		all_notifs = []
	all_notifs.sort(key=lambda n: getattr(n, 'created_at', None) or 0, reverse=True)
	# mark as seen
	for n in all_notifs:
		try:
			if not getattr(n, 'seen', False):
				n.seen = True
				n.save()
		except Exception:
			pass

	# compute my following for button states
	try:
		me_following = set(u.username for u in me.following.all())
	except Exception:
		me_following = set()

	def build(n: Notification) -> dict:
		base = {
			'uid': n.uid,
			'type': n.type,
			'from_username': n.from_username,
			'created_at': n.created_at.isoformat() if getattr(n, 'created_at', None) else '',
			'seen': getattr(n, 'seen', False),
			'target_uid': getattr(n, 'target_uid', '') or '',
			'element_type': getattr(n, 'element_type', '') or '',
		}
		if n.type == 'follow':
			base['icon'] = 'person'
			base['text'] = f"{n.from_username} te empezó a seguir"
			base['cta'] = 'follow'
			base['is_following'] = n.from_username in me_following
		elif n.type in ('like_post', 'like_comment'):
			base['icon'] = 'heart'
			target = 'publicación' if n.type == 'like_post' else 'comentario'
			base['text'] = f"{n.from_username} reaccionó a tu {target}"
			# derive post uid for comment
			post_uid = n.target_uid if n.element_type == 'post' else _resolve_post_uid_for_comment(n.target_uid)
			base['post_uid'] = post_uid
			base['cta'] = 'view_post' if n.type == 'like_post' else 'view_comment'
		elif n.type == 'comment_post':
			base['icon'] = 'comment'
			base['text'] = f"{n.from_username} comentó tu publicación"
			base['post_uid'] = _resolve_post_uid_for_comment(n.target_uid)
			base['cta'] = 'view_comment'
		elif n.type == 'reply_comment':
			base['icon'] = 'comment'
			base['text'] = f"{n.from_username} respondió a tu comentario"
			base['post_uid'] = _resolve_post_uid_for_comment(n.target_uid)
			base['cta'] = 'view_comment'
		else:
			base['icon'] = 'bell'
			base['text'] = f"{n.from_username} tiene una actualización"
			base['cta'] = None
		return base

	notifs_ctx = [build(n) for n in all_notifs]
	return render(request, 'notifications.html', { 'notifications': notifs_ctx })


def post_detail_view(request: HttpRequest, post_uid: str) -> HttpResponse:
	maybe = _login_required(request)
	if maybe:
		return maybe
	try:
		post = Post.nodes.get(uid=post_uid)
	except Post.DoesNotExist:
		return HttpResponse(status=404)
	me_username = _get_logged_in_username(request)
	me = _get_user_by_username(me_username)
	try:
		following_set = set(u.username for u in (list(me.following.all()) if me else []))
	except Exception:
		following_set = set()
	post_ctx = _serialize_post_card(post, following_usernames=following_set, me_username=me_username)
	comment_to_open = request.GET.get('comment', '')
	return render(request, 'post_detail.html', { 'post': post_ctx, 'comment_to_open': comment_to_open })
