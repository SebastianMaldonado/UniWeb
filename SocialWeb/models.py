from django.db import models  # Not used for our User node, kept for potential future Django models
from neomodel import StructuredNode, StringProperty, UniqueIdProperty, DateTimeProperty


class User(StructuredNode):
	"""User node stored in Neo4j via neomodel.

	Fields:
	- uid: internal unique id (UUID string)
	- username: unique username (letters, numbers, underscore)
	- email: unique email
	- password_hash: Django-compatible password hash
	- created_at: node creation timestamp
	"""

	uid = UniqueIdProperty()
	username = StringProperty(unique_index=True, required=True)
	email = StringProperty(unique_index=True, required=True)
	password_hash = StringProperty(required=True)
	created_at = DateTimeProperty(default_now=True)

	def __str__(self) -> str:  # pragma: no cover - helper only
		return f"User(username={self.username})"
