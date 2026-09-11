"""
URL configuration for inventory_pos project.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path

admin.site.site_header = 'Inventory POS'
admin.site.site_title = 'Inventory POS'
admin.site.index_title = 'Administration'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('logout/', LogoutView.as_view(next_page='/admin/login/'), name='logout'),
    path('pos/', include('pos.urls')),
    path('', include('inventory.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
