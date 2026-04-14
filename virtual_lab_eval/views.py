from django.http import HttpResponse, JsonResponse
from django.utils import timezone


def ping(request):
    """Public keep-alive endpoint for uptime monitoring services."""
    if request.GET.get("format") == "text":
        return HttpResponse("Server is alive", content_type="text/plain")

    return JsonResponse(
        {
            "status": "alive",
            "time": timezone.now().isoformat(),
            "message": "Server is alive",
        }
    )
