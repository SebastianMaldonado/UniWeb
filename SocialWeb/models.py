from django.db import models  # Not used for our User node, kept for potential future Django models
from neomodel import (
	StructuredNode,
	StringProperty,
	UniqueIdProperty,
	DateTimeProperty,
	DateProperty,
	RelationshipTo,
	RelationshipFrom,
)


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

	# Profile fields
	profile_image_url = StringProperty(required=False)
	cover_image_url = StringProperty(required=False)
	gender = StringProperty(required=False)  # e.g., 'masculino', 'femenino', 'otro'
	bio = StringProperty(required=False)
	birthdate = DateProperty(required=False)

	# Social graph
	following = RelationshipTo('User', 'FOLLOWS')
	followers = RelationshipFrom('User', 'FOLLOWS')

	def __str__(self) -> str:  # pragma: no cover - helper only
		return f"User(username={self.username})"
