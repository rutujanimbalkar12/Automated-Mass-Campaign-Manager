import logging
from celery import shared_task
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from .models import EmailCampaign, CampaignLog

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def send_campaign_emails_task(self, campaign_id):
    try:
        campaign = EmailCampaign.objects.select_related('contact_list', 'template').get(id=campaign_id)
    except EmailCampaign.DoesNotExist:
        logger.error(f"[Task Error] Campaign #{campaign_id} does not exist.")
        return f"Campaign #{campaign_id} not found."

    if campaign.status != 'READY':
        logger.warning(f"[Task Skip] Campaign #{campaign.id} is '{campaign.status}', not 'READY'. Dispatch aborted.")
        return f"Campaign #{campaign.id} is not in READY state."

    subscribers = list(campaign.contact_list.subscribers.all())
    total_recipients = len(subscribers)

    if total_recipients == 0:
        logger.warning(f"[Task Abort] Contact list for campaign #{campaign.id} has no subscribers.")
        campaign.status = 'DRAFT'
        campaign.save(update_fields=['status'])
        return f"Campaign #{campaign.id} aborted: Audience list is empty."

    campaign.status = 'SENDING'
    campaign.total_recipients = total_recipients
    campaign.sent_count = 0
    campaign.save(update_fields=['status', 'total_recipients', 'sent_count'])

    template = campaign.template
    sent_successful = 0
    logs_to_create = []

    for subscriber in subscribers:
        sub_name = subscriber.name.strip() if subscriber.name else 'Valued Customer'
        sub_email = subscriber.email.strip()

        personalized_subject = template.subject.replace('{{name}}', sub_name).replace('{{email}}', sub_email)
        personalized_body = template.body.replace('{{name}}', sub_name).replace('{{email}}', sub_email)

        delivery_status = 'SENT'
        try:
            send_mail(
                subject=personalized_subject,
                message=personalized_body,
                from_email=None,
                recipient_list=[sub_email],
                fail_silently=False
            )
            sent_successful += 1
        except Exception as exc:
            logger.exception(f"[Delivery Failed] Could not dispatch to {sub_email}: {exc}")
            delivery_status = 'FAILED'

        logs_to_create.append(
            CampaignLog(
                campaign=campaign,
                recipient_email=sub_email,
                status=delivery_status,
                timestamp=timezone.now()
            )
        )

    with transaction.atomic():
        CampaignLog.objects.bulk_create(logs_to_create)
        campaign.sent_count = sent_successful
        campaign.status = 'COMPLETED'
        campaign.save(update_fields=['sent_count', 'status'])

    logger.info(f"[Task Completed] Campaign #{campaign.id} finished. Delivered: {sent_successful}/{total_recipients}")
    return f"Campaign #{campaign.id} completed. {sent_successful}/{total_recipients} sent."