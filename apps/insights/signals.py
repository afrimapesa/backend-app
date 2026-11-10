from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from . import front
from .models import Advertisement, Article, Author


@receiver([post_save, post_delete], sender=Article)
@receiver([post_save, post_delete], sender=Author)
@receiver([post_save, post_delete], sender=Advertisement)
@receiver(m2m_changed, sender=Article.countries.through)
def drop_front_page(**kwargs) -> None:
    """Any editorial or ad change shows on the front page as soon as it is committed."""
    transaction.on_commit(front.invalidate)
