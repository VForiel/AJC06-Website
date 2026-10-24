from django.contrib.syndication.views import Feed
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .models import Post


def post_list(request):
    page = Paginator(Post.objects.live(), 9).get_page(request.GET.get("page"))
    return render(request, "blog/list.html", {"page": page})


def post_detail(request, slug):
    qs = Post.objects.all() if request.user.is_staff else Post.objects.live()
    post = get_object_or_404(qs, slug=slug)
    newer = Post.objects.live().filter(published_at__gt=post.published_at).order_by("published_at").first()
    older = Post.objects.live().filter(published_at__lt=post.published_at).first()
    return render(request, "blog/detail.html", {"post": post, "newer": newer, "older": older})


class LatestPosts(Feed):
    title = _("AJC06 — actualités")
    description = _("Les actualités de l'Association des Jeunes Chercheurs des Alpes-Maritimes.")

    def link(self):
        return reverse("blog:list")

    def items(self):
        return Post.objects.live()[:20]

    def item_title(self, item):
        return item.title_tr

    def item_description(self, item):
        return item.teaser

    def item_pubdate(self, item):
        return item.published_at
