from django.db import models
from django.contrib.auth.models import User


class ContactList(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contact_lists')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Subscriber(models.Model):
    contact_list = models.ForeignKey(ContactList, on_delete=models.CASCADE, related_name='subscribers')
    name = models.CharField(max_length=200, blank=True, null=True)
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('contact_list', 'email')

    def __str__(self):
        return f"{self.email} ({self.contact_list.name})"


class EmailTemplate(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='templates')
    title = models.CharField(max_length=200)
    subject = models.CharField(max_length=255)
    body = models.TextField(help_text="Use {{name}} and {{email}} for dynamic tags.")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class EmailCampaign(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('READY', 'Ready'),
        ('SENDING', 'Sending in Background'),
        ('COMPLETED', 'Completed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='campaigns')
    name = models.CharField(max_length=200)
    contact_list = models.ForeignKey(ContactList, on_delete=models.CASCADE, related_name='campaigns')
    template = models.ForeignKey(EmailTemplate, on_delete=models.CASCADE, related_name='campaigns')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='DRAFT')
    sent_count = models.PositiveIntegerField(default=0)
    total_recipients = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} [{self.status}]"


class CampaignLog(models.Model):
    campaign = models.ForeignKey(EmailCampaign, on_delete=models.CASCADE, related_name='logs')
    recipient_email = models.EmailField()
    status = models.CharField(max_length=40, default='SENT')
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.campaign.name} -> {self.recipient_email} [{self.status}]"