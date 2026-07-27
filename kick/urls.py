from django.contrib import admin
from django.urls import path
from django.contrib.auth.views import LogoutView
from dashboard import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.svodka, name='svodka'),
    path('prodazhi/', views.prodazhi, name='prodazhi'),
    path('debitorka/', views.debitorka, name='debitorka'),
    path('upakovka/', views.upakovka, name='upakovka'),
    path('debitorka/<path:client>/', views.debtor, name='debtor'),
    path('upload/', views.upload, name='upload'),
    path('login/', views.Login.as_view(), name='login'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
]
