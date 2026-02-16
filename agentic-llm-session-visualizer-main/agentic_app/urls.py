"""URL configuration for Agentic Thinking Visualization."""

from django.urls import path
from visualization import views

urlpatterns = [
    path('', views.home, name='home'),
    path('visualization/', views.agentic_thinking_visualization_view, name='agentic_thinking_visualization'),
    path('logs/', views.log_manager_view, name='log_manager'),
    path('instructions/', views.instructions_view, name='instructions'),
]
