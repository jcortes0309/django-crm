# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# $Id: forms.py 425 2009-07-14 03:43:01Z tobias $
# ----------------------------------------------------------------------------
#
#    Copyright (C) 2008-2009 Caktus Consulting Group, LLC
#
#    This file is part of django-crm and was originally extracted from minibooks.
#
#    django-crm is published under a BSD-style license.
#    
#    You should have received a copy of the BSD License along with django-crm.  
#    If not, see <http://www.opensource.org/licenses/bsd-license.php>.
#

import datetime

from django import forms
from django.contrib.auth.models import User
from django.contrib.localflavor.us import forms as us_forms
from django.db import transaction
from django.db.models import Q

from caktus.django.forms import SimpleUserForm, RequestForm, RequestModelForm
from caktus.django.widgets import CheckboxSelectMultipleWithJS
from caktus.decorators import requires_kwarg
from caktus.django import widgets as caktus_widgets

import crm.models as crm

class PersonForm(SimpleUserForm):
    def clean_email(self):
        if not self.instance.id and \
          User.objects.filter(email=self.cleaned_data['email']).count() > 0:
            raise forms.ValidationError('A user with that e-mail address already exists.')
        return self.cleaned_data['email']


class ProfileForm(forms.ModelForm):
    """
    Model form for user profiles.
    """
    
    class Meta:
        model = crm.Profile
        fields = ('notes', 'picture')
    
    @transaction.commit_on_success
    def save(self, user):
        instance = super(ProfileForm, self).save(commit=False)
        new_instance = not instance.id
        instance.user = user
        instance.save()
        self.save_m2m()
        return instance
    
    
class PhoneForm(forms.ModelForm):
    """
    Model form for Phones.  The required type argument to __init__ should be
    one of the types defined in Phone.PHONE_TYPES, and the label on the
    form field will be set accordingly.  The profile is passed into save()
    instead of __init__ because it may not exist at the time __init__
    is called.
    """
    
    class Meta:
        model = crm.Phone
        fields = ('number', )
    
    @requires_kwarg('type')
    def __init__(self, *args, **kwargs):
        self.type = kwargs.pop('type')
        super(PhoneForm, self).__init__(*args, **kwargs)
        
        self.fields['number'].label = \
          dict(crm.Phone.PHONE_TYPES)[self.type]
        if self.type != 'fax':
            self.fields['number'].label += " phone"
        self.fields['number'].required = False
        
    @transaction.commit_on_success
    def save(self, profile):
        instance = super(PhoneForm, self).save(commit=False)
        new_instance = not instance.id
        if self.cleaned_data['number']:
            instance.profile = profile
            instance.type = self.type
            instance.save()
            self.save_m2m()
        else:
            if not new_instance:
                # if the number was removed, delete the instance
                instance.delete()
            instance = None
        return instance


class EmailForm(forms.Form):
    to = forms.ChoiceField()
    memo = forms.CharField(max_length=4096, widget=forms.Textarea)
    
    def clean_to(self):
        try:
            return User.objects.get(pk=self.cleaned_data['to'])
        except User.DoesNotExist:
            raise forms.ValidationError(_(u'This username is already taken. Please choose another.'))
        
        return self.cleaned_data['to']
    
    def __init__(self, *args, **kwargs):
        search = None
        
        business = kwargs.pop('business', None)
        project = kwargs.pop('project', None)
        
        if project:
            # ignore business contacts if a project is set
            search = Q(projects=project)
        elif business:
            search = Q(businesses=business)
        
        forms.Form.__init__(self, *args, **kwargs)
        
        if search:
            self.fields['to'].choices = []
            for user in User.objects.filter(search):
                choice = (user.id, "%s (%s)" % (user.get_full_name(), user.email))
                self.fields['to'].choices.append(choice)


class UserModelChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return obj.get_full_name()

class InteractionForm(RequestModelForm):
    class Meta:
        model = crm.Interaction
        fields = ('date', 'type', 'completed', 'project', 'contacts', 'memo',)
    
    def __init__(self, *args, **kwargs):    
        self.url = kwargs.pop('url')
        self.person = kwargs.pop('person')
        self.crm_user = kwargs.pop('crm_user')
        super(InteractionForm, self).__init__(*args, **kwargs)
        self.fields.keyOrder = \
            ('date', 'type', 'completed', 'contacts', 'project', 'memo',)
        
        self.fields['contacts'] = UserModelChoiceField(
            widget=caktus_widgets.AjaxSelectMultiWidget(url=self.url),
            queryset=User.objects.all(),
        )
        if not self.request.POST:
            if self.instance.id:
                initial_choices = \
                    self.instance.contacts.values_list('id', flat=True)
            else:
                initial_choices = [self.person.user.id, self.crm_user.id]
            self.fields['contacts'].widget.initial_choices = \
                [unicode(choice) for choice in initial_choices]
        
        if not self.instance.id and self.person:
            projects = crm.Project.objects.filter(contacts__profile=self.person)
        elif self.instance.id:
            # show only client projects
            client_contacts = self.instance.contacts.filter(
                businesses__business_types__name__iexact='client'
            )
            projects = crm.Project.objects.filter(
                contacts__in=client_contacts
            ).distinct()
        else:
            projects = crm.Project.objects.none()
        
        self.fields['project'].queryset = projects
        
        self.fields['date'].widget = caktus_widgets.MooDate()
        self.fields['date'].initial = datetime.datetime.now()
        
    def save(self):
        created = not self.instance.id
        instance = super(InteractionForm, self).save()
        if created:
            if self.person:
                instance.contacts.add(self.person.user)
            if self.crm_user:
                instance.contacts.add(self.crm_user)
        return instance


class SearchForm(forms.Form):
    search = forms.CharField(required=False)


class BusinessForm(forms.ModelForm):
    class Meta:
        model = crm.Business
        fields = ('name', 'notes', 'business_types')
    
    def __init__(self, *args, **kwargs):
        super(BusinessForm, self).__init__(*args, **kwargs)
        
        self.fields['business_types'].label = 'Type(s)'
        self.fields['business_types'].widget = \
          caktus_widgets.CheckboxSelectMultipleWithJS(
            choices = self.fields['business_types'].choices
        )
        self.fields['business_types'].help_text = '' 


class ProjectForm(forms.ModelForm):
    class Meta:
        model = crm.Project
        fields = (
            'name',
            'business',
            'trac_environment',
            'point_person',
            'type',
            'status',
            'description',
        )

    @requires_kwarg('business')
    def __init__(self, *args, **kwargs):
        self.business = kwargs.pop('business')
        super(ProjectForm, self).__init__(*args, **kwargs)
        
        if self.business:
            self.fields.pop('business')
        else:
            self.fields['business'].queryset = crm.Business.clients.all()
    
    def save(self):
        instance = super(ProjectForm, self).save(commit=False)
        if self.business:
            instance.business = self.business
        instance.save()
        return instance


class AddressForm(forms.ModelForm):
    """
    Model form for US postal addresses.
    """
    class Meta:
        model = crm.Address
        fields = ('street', 'city', 'state', 'zip',)
    
    def __init__(self, *args, **kwargs):
        super(AddressForm, self).__init__(*args, **kwargs)


class ProjectRelationshipForm(RequestModelForm):
    class Meta:
        model = crm.ProjectRelationship
        fields = ('types')
    
    def __init__(self, *args, **kwargs):
        super(ProjectRelationshipForm, self).__init__(*args, **kwargs)
        self.fields['types'].widget = forms.CheckboxSelectMultiple(
            choices=self.fields['types'].choices
        )
        self.fields['types'].help_text = ''
