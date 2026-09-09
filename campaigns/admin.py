from django.contrib import admin
from .models import ContactList, Subscriber, EmailTemplate, EmailCampaign, CampaignLog

admin.site.register(ContactList)
admin.site.register(Subscriber)
admin.site.register(EmailTemplate)
admin.site.register(EmailCampaign)
admin.site.register(CampaignLog)