from django import forms
from .models import ContactList, Subscriber, EmailTemplate, EmailCampaign


class ContactListForm(forms.ModelForm):
    class Meta:
        model = ContactList
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., VIP Customers'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'List description...'}),
        }


class SubscriberForm(forms.ModelForm):
    class Meta:
        model = Subscriber
        fields = ['name', 'email']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'John Doe'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'john@example.com'}),
        }


class SubscriberUploadForm(forms.Form):
    file = forms.FileField(
        label="Select CSV File",
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': '.csv'
        })
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data.get('file')
        if uploaded_file and not uploaded_file.name.lower().endswith('.csv'):
            raise forms.ValidationError("Invalid file format. Please upload a .csv file.")
        return uploaded_file


class EmailTemplateForm(forms.ModelForm):
    class Meta:
        model = EmailTemplate
        fields = ['title', 'subject', 'body']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Diwali Offer Template'}),
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Special Diwali Offer 🎉'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 6, 'placeholder': 'Hello {{name}},\n\nGet 30% OFF this Diwali!'}),
        }


class EmailCampaignForm(forms.ModelForm):
    class Meta:
        model = EmailCampaign
        fields = ['name', 'contact_list', 'template', 'status']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Diwali Special Offer'}),
            'contact_list': forms.Select(attrs={'class': 'form-select'}),
            'template': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['contact_list'].queryset = ContactList.objects.filter(user=user)
            self.fields['template'].queryset = EmailTemplate.objects.filter(user=user)