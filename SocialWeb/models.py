from django.db import models  # Not used for our User node, kept for potential future Django models
from neomodel import (
	StructuredNode,
	StringProperty,
	UniqueIdProperty,
	DateTimeProperty,
	DateProperty,
	JSONProperty,
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


class Post(StructuredNode):
	"""Post node representing a publication in the network."""
	uid = UniqueIdProperty()
	title = StringProperty(required=True)
	description = StringProperty(required=False)  # enforce max 500 in views
	images = JSONProperty(default=list)  # list[str] of image URLs
	links = JSONProperty(default=list)   # list[str] of URLs
	hashtags = JSONProperty(default=list)  # list[str]
	author_username = StringProperty(required=True, index=True)
	author_uid = StringProperty(required=True, index=True)
	created_at = DateTimeProperty(default_now=True, index=True)

	# Relationships
	author = RelationshipTo('User', 'AUTHORED_BY')
	comments = RelationshipTo('Comment', 'HAS_COMMENT')
	liked_by = RelationshipFrom('User', 'LIKED_POST')

	def __str__(self) -> str:  # pragma: no cover
		return f"Post(title={self.title}, author={self.author_username})"


class Comment(StructuredNode):
	"""Comment node with support for nested replies."""
	uid = UniqueIdProperty()
	text = StringProperty(required=True)  # enforce limits in views
	author_username = StringProperty(required=True, index=True)
	author_uid = StringProperty(required=True, index=True)
	created_at = DateTimeProperty(default_now=True, index=True)

	# Relationships
	on_post = RelationshipFrom('Post', 'HAS_COMMENT')
	on_comment = RelationshipFrom('Comment', 'HAS_REPLY')
	replies = RelationshipTo('Comment', 'HAS_REPLY')
	liked_by = RelationshipFrom('User', 'LIKED_COMMENT')

	def __str__(self) -> str:  # pragma: no cover
		return f"Comment(author={self.author_username}, text={self.text[:20]!r})"
