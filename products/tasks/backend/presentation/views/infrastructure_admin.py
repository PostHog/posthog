from collections.abc import Callable
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from loginas.utils import is_impersonated_session
from pydantic import JsonValue

from products.tasks.backend.facade.infrastructure import DEV_STACK_IMAGE_NAME, IMAGE_NAMES, InfrastructureStatus


@require_GET
def infrastructure_admin(request: HttpRequest) -> HttpResponse:
    if not request.user.is_active or not request.user.is_staff or is_impersonated_session(request):
        raise PermissionDenied
    source = request.GET.get("source")
    if source is None:
        return render(
            request, "infrastructure_admin.html", {"js_url": settings.JS_URL, "region": settings.CLOUD_DEPLOYMENT}
        )
    collector = InfrastructureStatus()
    loaders: dict[str, Callable[[], JsonValue]] = {
        "package": collector.package,
        "release": collector.release,
        "custom": collector.custom_images,
        "dev_stack": collector.dev_stack,
    }
    if source in IMAGE_NAMES:
        loader = lambda: collector.registry(source)
    elif source == "workflow":
        image_id = request.GET.get("image_id", "")
        if image_id == "dev_stack":
            workflow_id = f"bake-dev-stack-image-{DEV_STACK_IMAGE_NAME}"
        else:
            try:
                parsed_id = UUID(image_id)
            except ValueError:
                return JsonResponse({"detail": "Invalid image ID"}, status=400)
            workflow_id = f"build-sandbox-image-{parsed_id}"
        source = f"workflow:{workflow_id}"
        loader = lambda: collector.workflow(workflow_id)
    elif source in loaders:
        loader = loaders[source]
    else:
        return JsonResponse({"detail": "Unknown source"}, status=400)
    return JsonResponse(collector.read(source, loader).model_dump(mode="json"))
