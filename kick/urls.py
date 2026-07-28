from django.contrib import admin
from django.urls import path
from django.contrib.auth.views import LogoutView
from dashboard import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.svodka, name='svodka'),
    path('prodazhi/', views.prodazhi, name='prodazhi'),
    path('debitorka/', views.debitorka, name='debitorka'),
    path('oplaty/', views.oplaty, name='oplaty'),
    path('oplaty/day/<day>/', views.oplaty_day, name='oplaty_day'),
    path('signals/', views.signals, name='signals'),
    path('sravnenie/', views.sravnenie, name='sravnenie'),
    path('sravnenie/drill/', views.sravnenie_drill, name='sravnenie_drill'),
    path('clients/', views.clients, name='clients'),
    path('clients/<path:client>/', views.client_card, name='client_card'),
    path('upakovka/', views.upakovka, name='upakovka'),
    path('debitorka/<path:client>/', views.debtor, name='debtor'),
    path('upload/', views.upload, name='upload'),
    path('login/', views.Login.as_view(), name='login'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
]
