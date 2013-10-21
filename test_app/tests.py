# -*- encoding: utf-8 -*-
import json
import time

from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _
from django.core.urlresolvers import reverse
from django_any import any_model
from django.conf import settings
from selenium_helpers import SeleniumTestCase, select_option_by_text, \
    get_selected_option, wd

from selenium.common.exceptions import InvalidSelectorException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.wait import WebDriverWait
from multiseek.logic import MULTISEEK_ORDERING_PREFIX, MULTISEEK_REPORT_TYPE
from multiseek.models import SearchForm
from multiseek import logic
from multiseek.logic import get_registry, RANGE_OPS, EQUAL, CONTAINS
import multiseek_registry
from multiseek.util import make_field
from multiseek.views import LAST_FIELD_REMOVE_MESSAGE
from multiseek.logic import OR
from models import Author


FRAME = "frame-0"
FIELD = 'field-0'


class MultiseekWebPage(wd()):
    """Helper functions, that take care of the multiseek form web page
    """

    def __init__(self, registry, *args, **kw):
        super(MultiseekWebPage, self).__init__(*args, **kw)
        self.registry = registry

    def get_frame(self, id):
        """Ta funkcja zwraca multiseekową "ramkę" po jej ID
        """
        frame = self.find_element_by_id(id)
        ret = dict()
        ret['frame'] = frame
        ret['add_field'] = frame.children()[0].children()[1]
        ret['add_frame'] = frame.children()[0].children()[2]
        ret['fields'] = frame.children()[0].children()[0].children()
        return ret

    def extract_field_data(self, element):
        """Ta funkcja zwraca słownik z wartościami dla danego pola w
        formularzu. Pole - czyli wiersz z kolejnymi selectami:

            pole przeszukiwane, operacja, wartość wyszukiwana,
            następna operacja, przycisk zamknięcia

        Z pomocniczych wartości, zwracanych w słowniku mamy 'type' czyli
        tekstowy typ, odpowiadający definicjom w bpp.multiseek.logic.fields.keys()

        Zwracana wartość słownika 'value' może być różna dla różnych typów
        pól (np dla multiseek.logic.RANGE jest to lista z wartościami z obu pól)
        """
        ret = {}
        for elem in ['field', 'operation', 'next_operation', 'close_button']:
            ret[elem] = element.find_elements_by_name(elem)[0]

        selected = get_selected_option(ret['field'])
        ret['selected'] = selected.text()

        inner_type = self.registry.field_by_name.get(selected.text()).type
        ret['type'] = inner_type

        if inner_type == logic.RANGE:
            v = [element.find_elements_by_name('value_min')[0],
                 element.find_elements_by_name('value_max')[0]]

        elif inner_type == logic.AUTOCOMPLETE:
            # v = element.children()[3] <-- SELECT z wartościami
            widget = element.children()[2]
            v = widget.children()[0] # INPUT do wpisywania tekstu

        elif inner_type == logic.VALUE_LIST:
            v = element.find_elements_by_name('value_list')[0]

        elif inner_type == logic.STRING:
            v = element.find_elements_by_name('value')[0]

        else:
            raise Exception("Unknown type: %r" % inner_type)

        ret['value'] = v
        return ret

    def get_field(self, id):
        field = self.find_element_by_id(id)
        return self.extract_field_data(field)

    def serialize(self):
        """Zwraca wartość funkcji serialize() dla formularza, w postaci
        listy -- czyli obiekt JSON"""
        return self.execute_script('''return serialize($('#frame-0'));''')

    def get_field_value(self, field):
        return self.execute_script("""
        return getFieldValue($("#%s"));
        """ % field)

    def add_field(self, frame, label, op, value):
        self.execute_script("""
        addField($("#%(frame)s"), "%(label)s", "%(op)s", %(value)s);
        """ % dict(frame=frame,
                   label=unicode(label),
                   op=unicode(op),
                   value=json.dumps(value)))

    def load_form_by_name(self, name):
        self.refresh()
        select = self.find_element_by_jquery("#formsSelector")
        for option in select.children():
            if option.text() == name:
                option.click()
                self.switch_to_alert().accept()
                return

        raise Exception("Form named %r not found" % name)

    def reset_form(self):
        self.find_element_by_id("resetFormButton").click()


class MultiseekPageMixin:
    url = reverse('multiseek:index')

    def get_page(self):
        self.registry = get_registry(settings.MULTISEEK_REGISTRY)
        return MultiseekWebPage(self.registry)


class TestMultiseekSelenium(MultiseekPageMixin, SeleniumTestCase):
    def test_multiseek(self):
        field = self.page.get_field(FIELD)
        # On init, the first field will be selected
        self.assertEquals(
            field['selected'], self.registry.fields[0].label)

    def test_change_field(self):
        field = self.page.get_field(FIELD)

        select_option_by_text(
            field['field'], unicode(multiseek_registry.YearQueryObject.label))
        field = self.page.get_field(FIELD)
        self.assertEquals(field['type'], logic.RANGE)
        self.assertEquals(len(field['value']), 2)

        select_option_by_text(
            field['field'],
            unicode(multiseek_registry.LanguageQueryObject.label))
        field = self.page.get_field(FIELD)
        self.assertEquals(field['type'], logic.VALUE_LIST)

        select_option_by_text(
            field['field'], unicode(multiseek_registry.AuthorQueryObject.label))
        field = self.page.get_field(FIELD)
        self.assertEquals(field['type'], logic.AUTOCOMPLETE)

    def test_serialize_form(self):
        frame = self.page.get_frame('frame-0')
        frame['add_field'].click()
        frame['add_field'].click()
        frame['add_field'].click()

        frame['add_frame'].click()
        frame['add_frame'].click()

        for n in range(2, 5):
            field = self.page.get_field('field-%i' % n)
            field['value'].send_keys('aaapud!')

        field = self.page.get_field('field-0')
        select_option_by_text(
            field['field'], multiseek_registry.YearQueryObject.label)
        field = self.page.get_field('field-0')
        field['value'][0].send_keys('1999')
        field['value'][1].send_keys('2000')
        select_option_by_text(field['next_operation'], "or")

        field = self.page.get_field('field-1')
        select_option_by_text(
            field['field'], multiseek_registry.LanguageQueryObject.label)
        field = self.page.get_field('field-1')
        select_option_by_text(field['value'], _(u'english'))

        self.maxDiff = None

        expected = [
            {u'field': _(u'Year'), u'operation': RANGE_OPS[0],
             u'value': [u'1999', u'2000']}, u'or',
            {u'field': _(u'Language'), u'operation': EQUAL,
             u'value': u'english'}, u'and',
            {u'field': _(u'Title'), u'operation': CONTAINS,
             u'value': u'aaapud!'}, u'and',
            {u'field': _(u'Title'), u'operation': CONTAINS,
             u'value': u'aaapud!'}, u'and',
            [{u'field': _(u'Title'), u'operation': CONTAINS,
              u'value': u'aaapud!'}], u'and',
            [{u'field': _(u'Title'), u'operation': CONTAINS, u'value': u''}]
        ]

        self.assertEquals(self.page.serialize(), expected)

        for n in range(1, 6):
            field = self.page.get_field('field-%i' % n)
            field['close_button'].click()

        expected = [{u'field': _(u'Year'), u'operation': _(u'in'),
                     u'value': [u'1999', u'2000']}]
        self.assertEquals(self.page.serialize(), expected)

    def test_remove_last_field(self):
        field = self.page.get_field('field-0')
        field['close_button'].click()

        self.assertEquals(
            self.page.switch_to_alert().text, LAST_FIELD_REMOVE_MESSAGE)

    def test_autocomplete_field(self):
        field = self.page.get_field(FIELD)
        select_option_by_text(
            field['field'], multiseek_registry.AuthorQueryObject.label)

        field = self.page.get_field(FIELD)

        field['value'].send_keys('smit')
        self.page.wait_for_selector(".yourlabs-autocomplete", True)

        field['value'].send_keys(Keys.ARROW_DOWN)
        field['value'].send_keys(Keys.RETURN)

        def f(selenium):
            elem = self.page.find_element_by_jquery(".yourlabs-autocomplete")
            return not elem.visible()

        WebDriverWait(self, 10).until(
            lambda driver: f(driver))

        got = self.page.serialize()
        expect = [make_field(
            multiseek_registry.AuthorQueryObject,
            EQUAL, unicode(Author.objects.filter(last_name='Smith')[0].pk))]

        self.assertEquals(got, expect)

    def test_set_join(self):
        self.page.execute_script("""
        set_join($("#field-0"), "or");
        """)

        ret = self.page.execute_script("""
        return get_join($("#field-0")).val();
        """)

        self.assertEquals(ret, "or")

        self.page.add_field(FRAME,
                            unicode(self.registry.fields[0].label),
                            unicode(self.registry.fields[0].ops[0]),
                            '')

        self.page.execute_script("""
        set_join($("#field-1"), "or");
        """)

        ret = self.page.execute_script("""
        return get_join($("#field-1")).val();
        """)

        self.assertEquals(ret, "or")

    def test_set_frame_join(self):
        self.page.execute_script("""
        addFrame($("#frame-0"));
        addFrame($("#frame-0"));
        set_join($("#frame-1"), "or");
        """)

        ret = self.page.execute_script("""
        return get_join($("#frame-1")).val();
        """)

        self.assertEquals(ret, "or")

    def test_add_field_value_list(self):
        self.page.add_field(
            FRAME,
            multiseek_registry.LanguageQueryObject.label,
            multiseek_registry.LanguageQueryObject.ops[1],
            unicode(_(u'polish')))

        field = self.page.get_field("field-1")
        self.assertEquals(
            field['field'].val(), multiseek_registry.LanguageQueryObject.label)
        self.assertEquals(
            field['operation'].val(),
            multiseek_registry.LanguageQueryObject.ops[1])
        self.assertEquals(field['value'].val(), unicode(_(u'polish')))

    def test_add_field_autocomplete(self):
        self.page.add_field(
            FRAME,
            multiseek_registry.AuthorQueryObject.label,
            multiseek_registry.AuthorQueryObject.ops[1],
            [1, 'John Smith'])

        field = self.page.get_field_value("field-1")
        self.assertEquals(field['value'], '1')

    def test_add_field_string(self):
        self.page.add_field(
            FRAME,
            multiseek_registry.TitleQueryObject.label,
            multiseek_registry.TitleQueryObject.ops[0],
            "aaapud!")

        field = self.page.get_field_value("field-1")
        self.assertEquals(field['value'], 'aaapud!')

    def test_add_field_range(self):
        self.page.add_field(
            FRAME,
            multiseek_registry.YearQueryObject.label,
            multiseek_registry.YearQueryObject.ops[0],
            [1000, 2000])

        field = self.page.get_field_value("field-1")
        self.assertEquals(field['value'], [u'1000', u'2000'])

    def test_refresh_bug(self):
        # There's a bug, that when you submit the form with "OR" operation,
        # and then you refresh the page, the operation is changed to "AND"

        frame = self.page.get_frame('frame-0')
        frame['add_field'].click()

        field = self.page.get_field("field-0")
        select_option_by_text(field['next_operation'], unicode(_("or")))
        self.assertEquals(field['next_operation'].val(), unicode(_("or")))

        button = self.page.find_element_by_id("sendQueryButton")
        button.click()

        time.sleep(0.5)

        self.reload()

        field = self.page.get_field("field-0")
        self.assertEquals(field['next_operation'].val(), unicode(_("or")))

    def test_frame_bug(self):
        self.page.find_elements_by_jquery("button#add_frame")[1].click()
        self.page.find_elements_by_jquery("input[name=close_button]")[1].click()
        self.page.find_element_by_jquery("button#sendQueryButton").click()
        self.page.switch_to_frame("if")
        print self.page.page_source
        self.assertNotIn("Server Error (500)", self.page.page_source)


class TestFormSaveAnonymous(MultiseekPageMixin, SeleniumTestCase):
    def test_initial(self):
        # Without SearchForm objects, the formsSelector is invisible
        elem = self.page.find_element_by_jquery("#formsSelector")
        self.assertEquals(elem.visible(), False)

    def test_initial_with_data(self):
        any_model(SearchForm, public=True)
        self.reload()
        elem = self.page.find_element_by_jquery("#formsSelector")
        self.assertEquals(elem.visible(), True)

    def test_form_save_anonymous(self):
        # Anonymous users cannot save forms:
        self.assertRaises(
            InvalidSelectorException,
            self.page.find_element_by_jquery, "#saveFormButton")


class TestPublicReportTypes(MultiseekPageMixin, SeleniumTestCase):
    def test_secret_report_invisible(self):
        elem = self.page.find_element_by_name("_ms_report_type")
        self.assertEquals(len(elem.children()), 2)

class LoggedInTestCase(SeleniumTestCase):
    def setUp(self):
        super(LoggedInTestCase, self).setUp()

        LOGIN = PASSWORD = "test"

        User.objects.create_superuser(
            username=LOGIN, password=PASSWORD, email='foo@bar.com')
        self.login_via_admin(LOGIN, PASSWORD, then=reverse("multiseek:index"))



class TestPublicReportTypesLoggedIn(MultiseekPageMixin, LoggedInTestCase):
    def test_secret_report_visible(self):
        elem = self.page.find_element_by_name("_ms_report_type")
        self.assertEquals(len(elem.children()), 3)


class TestFormSaveLoggedIn(MultiseekPageMixin, LoggedInTestCase):

    def test_save_form_logged_in(self):
        self.assertEquals(
            self.page.find_element_by_jquery("#saveFormButton").visible(),
            True)

    def click_save_button(self):
        button = self.page.find_element_by_jquery("#saveFormButton")
        button.click()

    def save_form_as(self, name):
        self.click_save_button()
        alert = self.page.switch_to_alert()
        alert.send_keys(name)
        alert.accept()

    def accept_alert(self):
        alert = self.page.switch_to_alert()
        alert.accept()
        time.sleep(1)

    def dismiss_alert(self):
        alert = self.page.switch_to_alert()
        alert.dismiss()
        time.sleep(0.5)

    def count_elements_in_form_selector(self, name):
        select = self.page.find_element_by_jquery("#formsSelector")
        self.assertEquals(select.visible(), True)
        passed = 0
        for option in select.children():
            if option.text() == name:
                passed += 1
        return passed

    def test_save_form_server_error(self):
        NAME = 'testowy formularz'
        self.page.execute_script("SAVE_FORM_URL='/unexistent';")
        # Zapiszmy formularz
        self.save_form_as(NAME)
        # ... pytanie, czy ma być publiczny:
        self.accept_alert()
        # ... po chwili informacja, że BŁĄD!
        self.accept_alert()
        # ... i selector się NIE pojawia:
        self.assertEquals(
            self.page.find_element_by_id('formsSelector').visible(), False)
        # ... i w bazie też PUSTKA:
        self.assertEquals(SearchForm.objects.all().count(), 0)


    def test_save_form_save(self):
        self.assertEquals(SearchForm.objects.all().count(), 0)

        self.click_save_button()
        alert = self.page.switch_to_alert()
        alert.dismiss()
        # Anulowanie nie powinno wyświetlić następnego formularza

        NAME = 'testowy formularz'

        # Zapiszmy formularz
        self.save_form_as(NAME)
        # ... pytanie, czy ma być publiczny:
        self.accept_alert()
        # ... po chwili informacja, że zapisano
        self.accept_alert()
        # ... i nazwa pojawia się w selectorze
        self.assertEquals(self.count_elements_in_form_selector(NAME), 1)
        # ... i w bazie:
        self.assertEquals(SearchForm.objects.all().count(), 1)

        # Zapiszmy formularz pod TĄ SAMĄ NAZWĄ
        self.save_form_as(NAME)
        # ... pytanie, czy ma być publiczny:
        self.accept_alert()
        # ... po chwili informacja, że jest już taki w bazie i czy nadpisać?
        self.accept_alert()
        # ... po chwili informacja, że zapisano:
        self.accept_alert()
        # ... i nazwa pojawia się w selectorze
        self.assertEquals(self.count_elements_in_form_selector(NAME), 1)
        # ... i w bazie jest nadal jeden
        self.assertEquals(SearchForm.objects.all().count(), 1)

        # Zapiszmy formularz pod TĄ SAMĄ NAZWĄ ale już NIE nadpisujemy
        self.save_form_as(NAME)
        # ... pytanie, czy ma być publiczny:
        self.accept_alert()
        # ... po chwili informacja, że jest już taki w bazie i czy nadpisać?
        self.accept_alert()
        # ... po chwili informacja, że ZAPISANY
        self.accept_alert()
        # ... i w bazie jest nadal jeden
        self.assertEquals(SearchForm.objects.all().count(), 1)
        # Sprawdźmy, czy jest publiczny
        self.assertEquals(SearchForm.objects.all()[0].public, True)

        # Nadpiszmy formularz jako nie-publiczny
        self.save_form_as(NAME)
        # ... pytanie, czy ma być publiczny:
        self.dismiss_alert()
        # ... po chwili informacja, że jest już taki w bazie i czy nadpisać?
        self.accept_alert()
        # ... po chwili informacja, że zapisano:
        self.accept_alert()
        # ... i jest to już NIE-publiczny:
        self.assertEquals(SearchForm.objects.all()[0].public, False)

    def test_load_form(self):
        fld = make_field(
            self.registry.fields[2],
            self.registry.fields[2].ops[1],
            [2000, 2010])
        SearchForm.objects.create(
            name="lol",
            owner=User.objects.all()[0],
            public=True,
            data=json.dumps({"form_data": [fld]}))

        self.page.load_form_by_name('lol')

        # SERVER ERROR 500 here and I don't know why!
        field = self.page.extract_field_data(
            self.page.find_element_by_id("field-0"))

        self.assertEquals(
            field['selected'], unicode(self.registry.fields[2].label))
        self.assertEquals(field['value'][0].val(), '2000')
        self.assertEquals(field['value'][1].val(), '2010')

        # Przetestuj, czy po ANULOWANIU select wróci do pierwotnej wartości
        select = self.page.find_element_by_jquery("#formsSelector")
        for option in select.children():
            if option.text() == 'lol':
                option.click()
                self.page.switch_to_alert().dismiss()
                break
        self.assertEquals(select.val(), "")

    def test_bug_2(self):
        f = self.registry.fields[0]
        v = self.registry.fields[0].ops[0]
        value = 'foo'

        field = make_field(f, v, value)

        form = [
            [field],
            OR,
            [field, OR, field, OR, field],
            OR,
            [field, OR, field, OR, field]
        ]

        SearchForm.objects.create(
            name="bug-2",
            owner=User.objects.all()[0],
            public=True,
            data=json.dumps({"form_data": form}))
        self.page.load_form_by_name('bug-2')
        elements = self.page.find_elements_by_jquery(
            '[name=next_operation]:visible')
        for elem in elements:
            if elem.css("visibility") != 'hidden':
                self.assertEquals(elem.val(), logic.OR)

    def test_save_ordering_direction(self):
        elem = "input[name=%s1_dir]" % MULTISEEK_ORDERING_PREFIX
        print elem
        print "X" * 90
        self.page.find_element_by_jquery(elem).click()
        self.save_form_as("foobar")
        # Should the dialog be public?
        self.accept_alert()
        # Form saved success
        self.accept_alert()

        self.page.reset_form()
        self.page.load_form_by_name("foobar")
        self.assertEquals(
            self.page.find_element_by_jquery("%s:checked" % elem).val(),
            "1")

    def test_save_ordering_box(self):
        elem = "select[name=%s0] option[value=2]" % MULTISEEK_ORDERING_PREFIX
        self.assertEquals(
            len(self.page.find_elements_by_jquery(elem + ":selected")),
            0)

        self.page.find_element_by_jquery(elem).attr("selected", "1")
        self.save_form_as("foobar")
        self.accept_alert()
        self.accept_alert()

        self.page.reset_form()
        self.page.load_form_by_name("foobar")
        self.assertEquals(
            len(self.page.find_elements_by_jquery(elem + ":selected")),
            1)

    def test_save_report_type(self):
        elem = "select[name=%s] option[value=1]" % MULTISEEK_REPORT_TYPE
        self.assertEquals(
            len(self.page.find_elements_by_jquery(elem + ":selected")),
            0)

        self.page.find_element_by_jquery(elem).attr("selected", "1")
        self.save_form_as("foobar")
        self.accept_alert()
        self.accept_alert()

        self.page.reset_form()
        self.page.load_form_by_name("foobar")
        self.assertEquals(
            len(self.page.find_elements_by_jquery(elem + ":selected")),
            1)