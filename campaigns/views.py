import csv
import io
from django.core.validators import EmailValidator
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import ContactList, Subscriber, EmailTemplate, EmailCampaign, CampaignLog
from .forms import (
    ContactListForm, 
    SubscriberForm, 
    EmailTemplateForm, 
    EmailCampaignForm, 
    SubscriberUploadForm
)
from .tasks import send_campaign_emails_task


# --- Authentication & Dashboard ---

def register_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = UserCreationForm()
    return render(request, 'campaigns/register.html', {'form': form})


def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('dashboard')
    else:
        form = AuthenticationForm()
    return render(request, 'campaigns/login.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def dashboard(request):
    context = {
        'total_lists': ContactList.objects.filter(user=request.user).count(),
        'total_subscribers': Subscriber.objects.filter(contact_list__user=request.user).count(),
        'total_templates': EmailTemplate.objects.filter(user=request.user).count(),
        'total_campaigns': EmailCampaign.objects.filter(user=request.user).count(),
        'ready_campaigns': EmailCampaign.objects.filter(user=request.user, status='READY').count(),
        'completed_campaigns': EmailCampaign.objects.filter(user=request.user, status='COMPLETED').count(),
    }
    return render(request, 'campaigns/dashboard.html', context)


# --- Contact Lists & Subscribers ---

@login_required
def contact_lists(request):
    if request.method == 'POST':
        form = ContactListForm(request.POST)
        if form.is_valid():
            contact_list = form.save(commit=False)
            contact_list.user = request.user
            contact_list.save()
            return redirect('contact_lists')
    else:
        form = ContactListForm()
    lists = ContactList.objects.filter(user=request.user)
    return render(request, 'campaigns/contact_lists.html', {'lists': lists, 'form': form})


@login_required
def contact_list_detail(request, pk):
    contact_list = get_object_or_404(ContactList, pk=pk, user=request.user)
    subscribers = contact_list.subscribers.all()
    return render(request, 'campaigns/contact_list_detail.html', {'contact_list': contact_list, 'subscribers': subscribers})


@login_required
def contact_list_delete(request, pk):
    contact_list = get_object_or_404(ContactList, pk=pk, user=request.user)
    if request.method == 'POST':
        contact_list.delete()
        return redirect('contact_lists')
    return render(request, 'campaigns/subscriber_confirm_delete.html', {'object': contact_list, 'type': 'List'})


@login_required
def subscriber_create(request, list_id):
    contact_list = get_object_or_404(ContactList, pk=list_id, user=request.user)
    if request.method == 'POST':
        form = SubscriberForm(request.POST)
        if form.is_valid():
            subscriber = form.save(commit=False)
            subscriber.contact_list = contact_list
            subscriber.save()
            return redirect('contact_list_detail', pk=contact_list.pk)
    else:
        form = SubscriberForm()
    return render(request, 'campaigns/subscriber_form.html', {'form': form, 'contact_list': contact_list})


@login_required
def subscriber_update(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk, contact_list__user=request.user)
    if request.method == 'POST':
        form = SubscriberForm(request.POST, instance=subscriber)
        if form.is_valid():
            form.save()
            return redirect('contact_list_detail', pk=subscriber.contact_list.pk)
    else:
        form = SubscriberForm(instance=subscriber)
    return render(request, 'campaigns/subscriber_form.html', {'form': form, 'contact_list': subscriber.contact_list})


@login_required
def subscriber_delete(request, pk):
    subscriber = get_object_or_404(Subscriber, pk=pk, contact_list__user=request.user)
    list_pk = subscriber.contact_list.pk
    if request.method == 'POST':
        subscriber.delete()
        return redirect('contact_list_detail', pk=list_pk)
    return render(request, 'campaigns/subscriber_confirm_delete.html', {'object': subscriber, 'type': 'Subscriber'})


@login_required
def subscriber_upload(request, pk):
    contact_list = get_object_or_404(ContactList, pk=pk, user=request.user)
    stats = None

    if request.method == 'POST':
        form = SubscriberUploadForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = form.cleaned_data['file']
            
            try:
                decoded_file = csv_file.read().decode('utf-8-sig').splitlines()
            except UnicodeDecodeError:
                messages.error(request, "Failed to decode CSV file. Ensure it is encoded in UTF-8.")
                return render(request, 'campaigns/subscriber_upload.html', {'contact_list': contact_list, 'form': form})

            if not decoded_file:
                messages.error(request, "The uploaded CSV file is empty.")
                return render(request, 'campaigns/subscriber_upload.html', {'contact_list': contact_list, 'form': form})

            reader = csv.DictReader(decoded_file)
            
            if not reader.fieldnames:
                messages.error(request, "Malformed CSV header. Missing columns.")
                return render(request, 'campaigns/subscriber_upload.html', {'contact_list': contact_list, 'form': form})
            
            fieldnames_clean = {k.strip().lower(): k for k in reader.fieldnames if k}
            if 'email' not in fieldnames_clean:
                messages.error(request, "CSV must contain an 'email' column header.")
                return render(request, 'campaigns/subscriber_upload.html', {'contact_list': contact_list, 'form': form})

            email_key = fieldnames_clean['email']
            name_key = fieldnames_clean.get('name')

            existing_emails = set(
                Subscriber.objects.filter(contact_list=contact_list)
                .values_list('email', flat=True)
            )
            existing_emails_lower = {e.lower() for e in existing_emails}

            seen_in_batch = set()
            new_subscribers = []
            imported_count = 0
            duplicates_count = 0
            invalid_count = 0
            email_validator = EmailValidator()

            for row in reader:
                if not any(row.values()):
                    continue

                raw_email = row.get(email_key, '')
                raw_name = row.get(name_key, '') if name_key else ''

                email = raw_email.strip() if raw_email else ''
                name = raw_name.strip() if raw_name else ''

                if not email:
                    invalid_count += 1
                    continue

                try:
                    email_validator(email)
                except ValidationError:
                    invalid_count += 1
                    continue

                email_lower = email.lower()

                if email_lower in existing_emails_lower or email_lower in seen_in_batch:
                    duplicates_count += 1
                    continue

                seen_in_batch.add(email_lower)
                new_subscribers.append(Subscriber(
                    contact_list=contact_list,
                    name=name,
                    email=email
                ))
                imported_count += 1

            if new_subscribers:
                Subscriber.objects.bulk_create(new_subscribers)

            stats = {
                'imported': imported_count,
                'duplicates': duplicates_count,
                'invalid': invalid_count,
                'total_members': contact_list.subscribers.count()
            }
            messages.success(request, f"Import processed: {imported_count} subscriber(s) added.")
    else:
        form = SubscriberUploadForm()

    return render(request, 'campaigns/subscriber_upload.html', {
        'contact_list': contact_list,
        'form': form,
        'stats': stats,
    })


# --- Templates ---

@login_required
def template_list(request):
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST)
        if form.is_valid():
            tmpl = form.save(commit=False)
            tmpl.user = request.user
            tmpl.save()
            return redirect('template_list')
    else:
        form = EmailTemplateForm()
    templates = EmailTemplate.objects.filter(user=request.user)
    return render(request, 'campaigns/template_list.html', {'templates': templates, 'form': form})


@login_required
def template_update(request, pk):
    template = get_object_or_404(EmailTemplate, pk=pk, user=request.user)
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            return redirect('template_list')
    else:
        form = EmailTemplateForm(instance=template)
    return render(request, 'campaigns/template_form.html', {'form': form, 'template': template})


@login_required
def template_delete(request, pk):
    template = get_object_or_404(EmailTemplate, pk=pk, user=request.user)
    if request.method == 'POST':
        template.delete()
        return redirect('template_list')
    return render(request, 'campaigns/subscriber_confirm_delete.html', {'object': template, 'type': 'Template'})


# --- Campaigns & Async Queue ---

@login_required
def campaign_list(request):
    if request.method == 'POST':
        form = EmailCampaignForm(request.POST, user=request.user)
        if form.is_valid():
            campaign = form.save(commit=False)
            campaign.user = request.user
            campaign.save()
            return redirect('campaign_list')
    else:
        form = EmailCampaignForm(user=request.user)
    campaigns = EmailCampaign.objects.filter(user=request.user).select_related('contact_list', 'template')
    return render(request, 'campaigns/campaign_list.html', {'campaigns': campaigns, 'form': form})


@login_required
def campaign_detail(request, pk):
    campaign = get_object_or_404(EmailCampaign, pk=pk, user=request.user)
    sample_sub = campaign.contact_list.subscribers.first()
    logs = campaign.logs.all().order_by('-timestamp')[:50]
    
    sample_name = sample_sub.name if (sample_sub and sample_sub.name) else 'Valued Customer'
    sample_email = sample_sub.email if sample_sub else 'user@example.com'
    
    preview_subject = campaign.template.subject.replace('{{name}}', sample_name).replace('{{email}}', sample_email)
    preview_body = campaign.template.body.replace('{{name}}', sample_name).replace('{{email}}', sample_email)

    return render(request, 'campaigns/campaign_detail.html', {
        'campaign': campaign,
        'preview_subject': preview_subject,
        'preview_body': preview_body,
        'sample_sub': sample_sub,
        'logs': logs,
    })


@login_required
def campaign_update(request, pk):
    campaign = get_object_or_404(EmailCampaign, pk=pk, user=request.user)
    if request.method == 'POST':
        form = EmailCampaignForm(request.POST, instance=campaign, user=request.user)
        if form.is_valid():
            form.save()
            return redirect('campaign_detail', pk=campaign.pk)
    else:
        form = EmailCampaignForm(instance=campaign, user=request.user)
    return render(request, 'campaigns/campaign_form.html', {'form': form, 'campaign': campaign})


@login_required
def campaign_delete(request, pk):
    campaign = get_object_or_404(EmailCampaign, pk=pk, user=request.user)
    if request.method == 'POST':
        campaign.delete()
        return redirect('campaign_list')
    return render(request, 'campaigns/subscriber_confirm_delete.html', {'object': campaign, 'type': 'Campaign'})


@login_required
def campaign_toggle_status(request, pk):
    campaign = get_object_or_404(EmailCampaign, pk=pk, user=request.user)
    if campaign.status in ['DRAFT', 'READY']:
        campaign.status = 'READY' if campaign.status == 'DRAFT' else 'DRAFT'
        campaign.save()
    return redirect('campaign_detail', pk=campaign.pk)


@login_required
def campaign_send_async(request, pk):
    campaign = get_object_or_404(EmailCampaign, pk=pk, user=request.user)
    
    if campaign.status == 'SENDING':
        messages.warning(request, "This campaign is currently being processed by Celery.")
        return redirect('campaign_detail', pk=campaign.pk)

    if campaign.status == 'COMPLETED':
        messages.info(request, "This campaign has already completed dispatching.")
        return redirect('campaign_detail', pk=campaign.pk)

    if campaign.status != 'READY':
        messages.error(request, "Campaign must be in 'READY' status before dispatching.")
        return redirect('campaign_detail', pk=campaign.pk)

    if campaign.contact_list.subscribers.count() == 0:
        messages.error(request, "Target audience list is empty. Add subscribers first.")
        return redirect('campaign_detail', pk=campaign.pk)

    send_campaign_emails_task.delay(campaign.id)
    messages.success(request, f"Task successfully queued in Redis. Background worker is dispatching {campaign.contact_list.subscribers.count()} emails.")
    return redirect('campaign_detail', pk=campaign.pk)