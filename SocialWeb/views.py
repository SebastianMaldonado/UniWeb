import re
from typing import Optional

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.contrib.auth.hashers import make_password, check_password

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
			return redirect("home")

	return render(request, "register.html", {"error": error})
