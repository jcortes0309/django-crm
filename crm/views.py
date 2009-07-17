# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# $Id: views.py 425 2009-07-14 03:43:01Z tobias $
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

from django.template import RequestContext, Context, loader
from django.shortcuts import get_object_or_404, render_to_response
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponseRedirect
from django.conf import settings
from django.core.urlresolvers import reverse
from django.utils import simplejson as json
from django.http import HttpResponse, Http404
from django.db.models import Q
from django.db import transaction
from django.contrib.auth.models import User

from caktus.django.forms import AutoCompleterForm
from caktus.django.decorators import render_with
from caktus.iter import all_true

from crm import models as crm
from crm import forms as crm_forms


@login_required
@render_with('crm/dashboard.html')
def dashboard(request):
    # soonest first
    upcoming_interactions = request.user.interactions.select_related(
        'cdr',
        'contacts',
        'project',
        'project__business',
    ).filter(completed=False).order_by('date')
    
    # most recent first
    recent_interactions = request.user.interactions.select_related(
        'cdr',
        'contacts',
        'project',
        'project__business',
    ).filter(completed=True)[:6]
    
    projects = request.user.projects.order_by(
        'name',
    ).select_related('business')
    
    context = {
        'recent_interactions': recent_interactions,
        'upcoming_interactions': upcoming_interactions,
        'projects': projects,
    }
    
    try:
        from ledger.models import Exchange
        # there are no permissions on this view, so all DB access
        # must filter by request.user
        context['recent_exchanges'] = Exchange.objects.filter(
            business__contacts=request.user
        ).select_related('type', 'business')[:10]
    except ImportError:
        pass
    
    return context

### not a view
def compare_by(fieldname):
    def compare_two_dicts(a, b):
        return cmp(a[fieldname], b[fieldname])
    return compare_two_dicts


@login_required
def quick_search(request):
    results = []
    if request.POST:
        if request.user.has_perm('crm.view_business'):
            for business in crm.Business.objects.filter(
                name__icontains=request.REQUEST['search'],
            ):
                results.append({
                    'label': business.name,
                    'href': reverse('view_business', kwargs={
                        'business_id': business.id,
                    }),
                    'element_class': 'business',
                })
        if request.user.has_perm('crm.view_project'):
            for project in crm.Project.objects.filter(
                name__icontains=request.REQUEST['search'],
            ).select_related():
                results.append({
                    'label': project.name,
                    'href': reverse('view_project', kwargs={
                        'business_id': project.business.id,
                        'project_id': project.id,
                    }),
                    'element_class': 'project',
                })
        if request.user.has_perm('crm.view_profile'):
            for profile in crm.Profile.objects.filter(
                Q(user__first_name__icontains=request.REQUEST['search']) | 
                Q(user__last_name__icontains=request.REQUEST['search']) |
                Q(user__email__icontains=request.REQUEST['search'])
            ).select_related():
                results.append({
                    'label': profile.user.get_full_name(),
                    'href': reverse('view_person', kwargs={'person_id': profile.id}),
                    'element_class': 'contact',
                })
                results.sort(compare_by('label'))
    return HttpResponse(json.dumps(results[:10]), mimetype="text/json")


@permission_required('crm.view_profile')
@render_with('crm/person/list.html')
def list_people(request):
    form = crm_forms.SearchForm(request.GET)
    if form.is_valid() and 'search' in request.GET:
        search = form.cleaned_data['search']
        people = crm.Profile.objects.filter(
            Q(user__first_name__icontains=search) |
            Q(user__last_name__icontains=search)
        )
        if people.count() == 1:
            return HttpResponseRedirect(
                reverse(
                    'view_person', 
                    kwargs={'person_id':people[0].id}
                )
            )
    else:
        people = crm.Profile.objects.all()
    
    context = {
        'form': form,
        # it'd be nice if we could grab 'phones' too, but that isn't supported:
        # http://code.djangoproject.com/ticket/6432
        'people': people.select_related('user').order_by('user__last_name'),
        'phone_types': crm.Phone.PHONE_TYPES,
    }
    return context


@permission_required('crm.view_profile')
@render_with('crm/person/view.html')
def view_person(request, person_id):
    try:
        person = crm.Profile.objects.select_related().get(pk=person_id)
    except crm.Profile.DoesNotExist:
        raise Http404
    
    interactions = person.user.interactions.order_by('-date').select_related(
        'contacts',
        'project',
        'project__business',
    )[0:10]
    
    context = {
        'person': person,
        'interactions': interactions,
    }
    return context


@permission_required('crm.add_profile')
@permission_required('crm.change_profile')
@transaction.commit_on_success
@render_with('crm/person/create_edit.html')
def create_edit_person(request, person_id=None):
    if person_id:
        profile = get_object_or_404(crm.Profile, pk=person_id)
        user = profile.user
        phones = dict((p.type, p) for p in profile.phones.all())
    else:
        user = None
        profile = None
        phones = {}
        
    phone_forms = []
    user_form = crm_forms.PersonForm(request, instance=user)
    if request.POST:
        profile_form = crm_forms.ProfileForm(request.POST, instance=profile)
        for type, display in crm.Phone.PHONE_TYPES:
            phone = phones.get(type, None)
            phone_form = crm_forms.PhoneForm(request.POST, instance=phone, type=type, prefix=type)
            phone_forms.append(phone_form)
        
        if user_form.is_valid() and profile_form.is_valid() and \
          all_true([phone_form.is_valid() for phone_form in phone_forms]):
            # no e-mail will be sent if dict is empty or None
            email = {
#                'template': 'path/to/email/template.txt',
#                'subject': 'Welcome!',
#                'extra_context': { 'somekey': 'someval' },
            }
            saved_user, user_created = user_form.save(email)
            saved_profile = profile_form.save(user=saved_user)
            for phone_form in phone_forms:
                phone_form.save(profile=saved_profile)
            
            if user:
                message = 'Person updated successfully'
            else:
                message = 'New person created successfully'
            request.user.message_set.create(message=message)
            
            if 'associate' in request.REQUEST:
                return HttpResponseRedirect(
                    '%s&associate=true&search_selection=user-%d' % (
                            request.REQUEST['associate'],
                            saved_user.id,
                        )
                )
            
            return HttpResponseRedirect(
                reverse(
                    'view_person',
                    kwargs={'person_id': saved_profile.id,},
                )
            )
    else:
        profile_form = crm_forms.ProfileForm(instance=profile)
        for type, display in crm.Phone.PHONE_TYPES:
            phone = phones.get(type, None)
            phone_forms.append(crm_forms.PhoneForm(type=type, prefix=type, instance=phone))
        
    context = {
        'forms': [user_form] + phone_forms + [profile_form],
        'user': user,
    }
    return context


@transaction.commit_on_success
@render_with('crm/person/register.html')
def register_person(request):
    form = crm_forms.PersonForm(request)
    if request.POST:
        if form.is_valid():
            email = {
                'template': 'crm/person/new_account_email.txt',
                'subject': 'Your minibooks account information',
                'extra_context': { 'app_url_base': settings.APP_URL_BASE },
            }
            user = form.save(email)
            return HttpResponseRedirect(reverse('auth_login'))

    context = {
        'form': form,
    }
    return context


# TODO make these use flot (or something else) and re-enable
# TODO remove links to Trac
#@login_required
#def graph(request, type, developer):
#    # XXX remove import *s
#    from trac_tickets.alchemy import *
#    from trac_tickets.graphs import *
#    from trac_tickets.models import TracConnection
#    
#    if type == 'developer_hours_sum':
#        developer_usernames = developers()
#        graph = graph_hours_sum(developer_usernames, 'PNG')
#    if type == 'commit_hours':
#        graph = graph_developer_hour_commits(developer)
#    if type == 'account':
#        account = Account.objects.get(id=developer)
#        graph = graph_account_sum(account, 'PNG')
#    
#    return HttpResponse(graph, mimetype='image/png')
#
#
#@login_required
#@render_with('crm/hours.html')
#def hours(request):
#    context = {
#        'graph_url' : reverse(
#            'graph_commit_hours',
#            kwargs={'developer': request.user.username,},
#        ),
#        'request' : request,
#    }
#    return context


@permission_required('crm.add_interaction')
@permission_required('crm.change_interaction')
@render_with('crm/interaction/create_edit.html')
def create_edit_interaction(request, person_id=None, interaction_id=None):
    if interaction_id:
        interaction = get_object_or_404(crm.Interaction, pk=interaction_id)
    else:
        interaction = None
    
    if person_id:
        person = get_object_or_404(crm.Profile, pk=person_id)
    else:
        person = None
    
    form = crm_forms.InteractionForm(
        request, 
        instance=interaction,
        person=person, 
        crm_user=request.user,
        url=reverse('quick_add_person'),
    )
    
    if request.POST and form.is_valid():
        form.save()
        return HttpResponseRedirect(reverse('list_interactions'))
    
    context = {
        'form': form,
        'person': person,
    }
    return context


@permission_required('crm.delete_interaction')
@render_with('crm/interaction/remove.html')
def remove_interaction(request, interaction_id):
    interaction = get_object_or_404(crm.Interaction, pk=interaction_id)
    
    if request.POST:
        interaction.delete()
        return HttpResponseRedirect(reverse('list_interactions'))
    
    context = {
        'interaction': interaction,
    }
    return context


@permission_required('crm.view_interaction')
@render_with('crm/interaction/list.html')
def list_interactions(request):
    form = crm_forms.SearchForm(request.GET)
    if form.is_valid():
        search = form.cleaned_data['search']
        interactions = crm.Interaction.objects.filter(
            Q(type__icontains=search) |
            Q(project__name__icontains=search) |
            Q(contacts__first_name__icontains=search) |
            Q(contacts__last_name__icontains=search) |
            Q(memo__icontains=search)
        ).distinct()
    #    if interactions.count() == 1:
    #        return HttpResponseRedirect(
    #            reverse(
    #                'view_interaction', 
    #                kwargs={'interaction_id':interactions[0].id}
    #            )
    #        )
    else:
        interactions = request.user.interactions.all()
        
    interactions = interactions.select_related(
        'cdr',
        'contacts',
        'project',
        'project__business',
    )
    
    context = {
        'form': form,
        'interactions': interactions,
    }
    return context


@permission_required('crm.view_business')
@render_with('crm/business/list.html')
def list_businesses(request):
    form = crm_forms.SearchForm(request.GET)
    if form.is_valid() and 'search' in request.GET:
        search = form.cleaned_data['search']
        businesses = crm.Business.objects.filter(
            Q(name__icontains=search) |
            Q(notes__icontains=search)
        )
        if businesses.count() == 1:
            return HttpResponseRedirect(
                reverse(
                    'view_business', 
                    kwargs={'business_id':businesses[0].id}
                )
            )
    else:
        businesses = crm.Business.objects.all()
    
    context = {
        'form': form,
        'businesses': businesses.select_related('address'),
    }
    return context


@permission_required('crm.view_business')
@render_with('crm/business/view.html')
def view_business(request, business):
    add_contact_form = AutoCompleterForm(
        url=reverse('quick_add_person'),
        options={
            'delay': 100,
            'markQuery': False,
            'autoSubmit': True,
            'forceSelect': True,
        },
    )
    context = {
        'business': business,
        'add_contact_form': add_contact_form,
    }
    
    try:
        from ledger.models import Exchange
        exchanges = Exchange.objects.filter(business=business)
        if business.projects.count() > 0:
            exchanges = exchanges.filter(
                Q(transactions__project__isnull=True) |
                ~Q(transactions__project__in=business.projects.all())
            )
        exchanges = exchanges.distinct().select_related().order_by(
            'type',
            '-date',
            '-id',
        )
        show_delivered_column = \
            exchanges.filter(type__deliverable=True).count() > 0
        context['exchanges'] = exchanges
        context['show_delivered_column'] = show_delivered_column
    except ImportError:
        pass
    
    return context


@permission_required('crm.add_business')
@permission_required('crm.change_business')
@render_with('crm/business/create_edit.html')
def create_edit_business(request, business=None):
    address = business and business.address or None
    
    if request.POST:
        def check_for_address():
            for field_name in ('city', 'zip', 'street'):
                if bool(request.POST[field_name]):
                    return True
            return False
        address_has_data = check_for_address()
        if address_has_data:
            address_form = crm_forms.AddressForm(
                request.POST,
                instance=address,
            )
        else:
            address_form = crm_forms.AddressForm()
        
        business_form = crm_forms.BusinessForm(
            request.POST,
            instance=business,
        )
        
        forms_valid = [business_form.is_valid()]
        if address_has_data:
            forms_valid.append(address_form.is_valid())
        if all_true(forms_valid):
            new_business = not business
            business = business_form.save(commit=False)
            if address_has_data:
                business.address = address_form.save()
            business.save()
            business_form.save_m2m()
            if new_business:
                return HttpResponseRedirect(
                    reverse(
                        'view_business',
                        kwargs={'business_id': business.id,},
                    ),
                )
            else:
                return HttpResponseRedirect(reverse('list_businesses'))
    else:
        business_form = crm_forms.BusinessForm(instance=business)
        address_form = crm_forms.AddressForm(instance=address)
    
    context = {
        'business': business,
        'address_form': address_form,
        'business_form': business_form,
    }
    return context


@permission_required('crm.view_project')
@render_with('crm/business/project/list.html')
def list_projects(request):
    form = crm_forms.SearchForm(request.GET)
    if form.is_valid() and 'search' in request.GET:
        search = form.cleaned_data['search']
        projects = crm.Project.objects.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search)
        )
        if projects.count() == 1:
            url_kwargs = {
                'business_id': projects[0].business.id,
                'project_id': projects[0].id,
            }
            return HttpResponseRedirect(
                reverse('view_project', kwargs=url_kwargs)
            )
    else:
        projects = crm.Project.objects.all()
    
    context = {
        'form': form,
        'projects': projects.select_related('business'),
    }
    return context


@permission_required('crm.view_project')
@transaction.commit_on_success
@render_with('crm/business/project/view.html')
def view_project(request, business, project):
    add_contact_form = AutoCompleterForm(
        url=reverse('quick_add_person'),
        options={
            'delay': 100,
            'markQuery': False,
            'autoSubmit': True,
            'forceSelect': True,
        },
    )
    
    context = {
        'project': project,
        'add_contact_form': add_contact_form,
    }
    try:
        from ledger.models import Exchange
        context['exchanges'] = Exchange.objects.filter(
            business=business,
            transactions__project=project,
        ).distinct().select_related().order_by('type', '-date', '-id',)
        context['show_delivered_column'] = \
            context['exchanges'].filter(type__deliverable=True).count() > 0
    except ImportError:
        pass
    
    return context


@permission_required('crm.change_business')
@permission_required('crm.change_project')
def quick_add_person(request):
    results = []
    if request.POST:
        for profile in crm.Profile.objects.filter(
            Q(user__first_name__icontains=request.REQUEST['search']) | 
            Q(user__last_name__icontains=request.REQUEST['search']) |
            Q(user__email__icontains=request.REQUEST['search'])
        ).select_related():
            results.append({
                'label': profile.user.get_full_name(),
                'element_class': 'contact',
                'element_id': unicode(profile.user.id),
            })
    
    return HttpResponse(json.dumps(results[:10]), mimetype="text/json")


@permission_required('crm.change_business')
@permission_required('crm.change_project')
@transaction.commit_on_success
def associate_contact(request, business, project=None, user_id=None, action=None):
    if action == 'add':
        if request.POST or 'associate' in request.REQUEST:
            try:
                user_id = request.REQUEST['search_selection']
            except (ValueError, KeyError):
                request.session.create_message(
                    'Your search for "%s" did not match any contacts. You\
                    may create a new contact here.' % request.POST['search'])
                return HttpResponseRedirect('%s?associate=%s' % \
                    (reverse('create_person'), request.get_full_path()))
            
            if user_id:
                try:
                    user = User.objects.get(pk=user_id)
                    if project:
                        crm.ProjectRelationship.objects.get_or_create(
                            user=user,
                            project=project,
                        )
                    else:
                        business.contacts.add(user)
                except User.DoesNotExist:
                    user = None
    else:
        try:
            user = User.objects.get(pk=user_id)
            if project:
                rel = crm.ProjectRelationship.objects.get(
                    user=user,
                    project=project,
                )
                rel.delete()
            else:
                business.contacts.remove(user)
        except User.DoesNotExist, crm.ProjectRelationship.DoesNotExist:
            user = None
    
    return HttpResponseRedirect(request.REQUEST['next'])


@permission_required('crm.change_project')
@transaction.commit_on_success
@render_with('crm/business/project/relationship.html')
def edit_project_relationship(request, business, project, user_id=None):
    user = get_object_or_404(User, id=user_id, projects=project)
    rel = crm.ProjectRelationship.objects.get(project=project, user=user)
    relationship_form = crm_forms.ProjectRelationshipForm(
        request,
        instance=rel,
    )
    if request.POST and relationship_form.is_valid():
        rel = relationship_form.save()
        return HttpResponseRedirect(request.REQUEST['next'])
    
    context = {
        'user': user,
        'project': project,
        'relationship_form': relationship_form,
    }
    return context


@permission_required('crm.add_project')
@permission_required('crm.change_project')
@render_with('crm/business/project/create_edit.html')
def create_edit_project(request, business=None, project=None):
    if request.POST:
        project_form = crm_forms.ProjectForm(
            request.POST,
            business=business,
            instance=project,
        )
        if project_form.is_valid():
            project = project_form.save()
            url_kwargs = {
                'business_id': project.business.id,
                'project_id': project.id,
            }
            return HttpResponseRedirect(
                reverse('view_project', kwargs=url_kwargs)
            )
    else:
        project_form = crm_forms.ProjectForm(
            business=business, 
            instance=project
        )
    
    context = {
        'business': business,
        'project': project,
        'project_form': project_form,
    }
    return context


@render_with('crm/person/address_book.xml')
def address_book(request, file_name):
    # WARNING: There is no security on this view.  Enable it with caution!
    address_book_enabled = getattr(settings, 'ADDRESS_BOOK_ENABLED', False)
    accepted_file_names = ('gs_phonebook.xml',)
    if address_book_enabled and file_name in accepted_file_names:
        contacts = crm.Profile.objects.select_related('phones', 'user').all()
        context = {
            'contacts': contacts,
        }
        return render_to_response(
            'crm/person/address_book.xml',
            context,
            mimetype='text/xml',
        )
    raise Http404
