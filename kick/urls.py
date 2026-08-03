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
    path('cost/', views.cost, name='cost'),
    path('cost/map/', views.cost_map, name='cost_map'),
    path('cost/channel/<code>/', views.cost_channel, name='cost_channel'),
    path('rfm/', views.rfm, name='rfm'),
    path('export/', views.export_xlsx, name='export'),
    path('managers/', views.managers, name='managers'),
    path('managers/<path:manager>/', views.manager_card, name='manager_card'),
    path('sravnenie/', views.sravnenie, name='sravnenie'),
    path('sravnenie/drill/', views.sravnenie_drill, name='sravnenie_drill'),
    path('clients/', views.clients, name='clients'),
    path('leads/', views.leads, name='leads'),
    path('leads/list/', views.leads_list, name='leads_list'),
    path('leads/stages/', views.lead_stages, name='lead_stages'),
    path('leads/import/', views.lead_import, name='lead_import'),
    path('leads/<int:lead_id>/move/', views.lead_move, name='lead_move'),
    path('leads/<int:lead_id>/delete/', views.lead_delete, name='lead_delete'),
    path('leads/<int:lead_id>/quick/', views.lead_quick, name='lead_quick'),
    path('leads/<int:lead_id>/', views.lead_card, name='lead_card'),
    path('clients/<path:client>/', views.client_card, name='client_card'),
    path('upakovka/', views.upakovka, name='upakovka'),
    path('debitorka/<path:client>/', views.debtor, name='debtor'),
    path('upload/', views.upload, name='upload'),
    path('login/', views.Login.as_view(), name='login'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
]
