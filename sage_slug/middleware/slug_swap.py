import logging

from django.conf import settings
from django.http import Http404
from django.http import HttpResponsePermanentRedirect as PermanentRedirect
from django.http import HttpResponseRedirect as TemporaryRedirect
from django.urls import NoReverseMatch, reverse
from django.utils.deprecation import MiddlewareMixin

from sage_slug.helpers.enums import RedirectType
from sage_slug.models import SlugSwap
from sage_slug.settings.conf import sageslug_config

logger = logging.getLogger(__name__)


class OldSlugRedirectMiddleware(MiddlewareMixin):
    """
    Middleware to handle old slug redirection.

    This middleware intercepts 404 responses and checks if the requested URL slug has
    been changed. If an old slug is detected, it attempts to find the new slug and
    redirects the user to the updated URL.

    The middleware dynamically retrieves the `SLUG_TYPE_MAPPING` from Django settings
    to determine the mappings between URL parameter names and their respective content types.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        super().__init__(get_response)
        self.slug_type_mapping = sageslug_config.slug_type_mapping

    def process_response(self, request, response):
        """
        Processes the response to check for 404 errors and handle old slug redirection.

        This method intercepts 404 responses, checks for old slugs in the request,
        and attempts to find and redirect to the new slug using the dynamically loaded
        SLUG_TYPE_MAPPING from settings.
        """
        if response.status_code == 404:
            try:
                updated_kwargs = {}

                for slug_name, slug_type in self.slug_type_mapping.items():
                    old_slug = request.resolver_match.kwargs.get(slug_name)
                    if old_slug:
                        updated_kwargs[slug_name] = self._get_new_slug(
                            old_slug, slug_type
                        )

                if updated_kwargs:
                    try:
                        new_url = reverse(
                            request.resolver_match.view_name, kwargs=updated_kwargs
                        )
                        return self._redirect(new_url, updated_kwargs)
                    except NoReverseMatch as e:
                        logger.error(
                            f"NoReverseMatch: {e} for view {request.resolver_match.view_name} with kwargs {updated_kwargs}"
                        )
                        raise Http404("Page not found.")

            except AttributeError as e:
                logger.warning(f"AttributeError: {e} in OldSlugRedirectMiddleware")
            except Exception as e:
                logger.error(f"Unexpected error: {e} in OldSlugRedirectMiddleware")

        return response

    def _get_new_slug(self, old_slug, slug_type):
        """
        Retrieves the new slug for the given old slug and content type.

        This method checks if there is a new slug associated with the given old slug
        and content type. If a new slug is found, it is returned; otherwise, the old
        slug is returned.
        """
        try:
            slug_swap = SlugSwap.objects.filter(
                old_slug=old_slug, content_type__model=slug_type
            ).first()
            if slug_swap:
                return slug_swap.new_slug
            return old_slug
        except SlugSwap.DoesNotExist:
            return old_slug
        except Exception as e:
            logger.error(
                f"Error retrieving new slug for {old_slug} of type {slug_type}: {e}"
            )
            return old_slug

    def _redirect(self, url, updated_kwargs):
        """
        Redirects to the new URL based on the updated slug.

        This method performs a redirection to the new URL constructed with the updated
        slug. It determines whether to perform a permanent or temporary redirect based
        on the redirect type defined in the SlugSwap model.

        The method dynamically determines which slug to query based on the SLUG_TYPE_MAPPING
        from settings.
        """
        try:
            old_slug = None
            for slug_name in self.slug_type_mapping.keys():
                if slug_name in updated_kwargs:
                    old_slug = updated_kwargs[slug_name]
                    break

            if old_slug:
                slug_swap = SlugSwap.objects.filter(old_slug=old_slug).first()
                if slug_swap:
                    if slug_swap.redirect_type == RedirectType.Primary:
                        return PermanentRedirect(url)
                    else:
                        return TemporaryRedirect(url)

            return TemporaryRedirect(url)
        except Exception as e:
            logger.error(
                f"Error during redirect to {url} with kwargs {updated_kwargs}: {e}"
            )
            return TemporaryRedirect(url)