import re
from typing import Optional
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

from .models import User


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


def home(request: HttpRequest) -> HttpResponse:
	if not _get_logged_in_username(request):
		return redirect("login")
	return render(request, "home.html")


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

		if not error and gender and gender not in genders:
			error = "Género inválido."

		# Validate birthdate as YYYY-MM-DD
		if not error and birthdate:
			try:
				# Let the browser send ISO date, we store as string parsing handled by neomodel DateProperty
				from datetime import date
				parts = [int(p) for p in birthdate.split("-")]
				if len(parts) == 3:
					date(parts[0], parts[1], parts[2])
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
			user.birthdate = birthdate or None
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
