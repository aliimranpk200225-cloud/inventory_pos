"""
URL configuration for inventory_pos project.
"""
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'Inventory POS'
admin.site.site_title = 'Inventory POS'
admin.site.index_title = 'Administration'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('pos/', include('pos.urls')),
    path('', include('inventory.urls')),
]
