"""Golden-file тесты загрузчика продаж: номер счёта, перенос корректировки в месяц отгрузки,
валидация структуры, безопасность частичной перезаливки. Синтетические xlsx строятся в памяти.
Запуск: manage.py test dashboard
"""
import datetime
from io import BytesIO
import openpyxl
from django.test import TestCase
from dashboard import loader
from dashboard.models import SalesFact


HEADER = ['Документ', 'Дата', 'Контрагент', 'Менеджер', 'июль 26', '', 'авг. 26', '']
SUB = ['Документ.Основание', '', '', '', 'Количество', 'Сумма', 'Количество', 'Сумма']


def _wb(header, sub, data):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Лист_1'
    ws.append(header)
    ws.append(sub)
    for r in data:
        ws.append(r)
    b = BytesIO()
    wb.save(b)
    b.seek(0)
    b.name = 'test.xlsx'
    return b


class SalesLoaderTests(TestCase):

    def test_schet_and_correction_reassigned_to_shipment(self):
        data = [
            ['Реализация (акт, накладная, УПД) № ФР150726/1 от 15.07.2026',
             datetime.datetime(2026, 7, 15), 'КЛИЕНТ А', 'Менеджер М', 10, 1000, None, None],
            ['Счет покупателю 00БП-000500 от 10.07.2026', None, None, None, 10, 1000, None, None],
            # корректировка сделана 3 августа, но на июльскую отгрузку ФР150726/1
            ['Корректировка реализации № ФР030826/K1 от 03.08.2026',
             datetime.datetime(2026, 8, 3), 'КЛИЕНТ А', 'Менеджер М', None, None, -2, -200],
            [None, None, None, None, None, None, -2, -200],
            ['Реализация (акт, накладная, УПД) ФР150726/1 от 15.07.2026',
             None, None, None, None, None, -2, -200],
        ]
        r = loader.load_sales_client(_wb(HEADER, SUB, data), 'test.xlsx', force=True)
        self.assertFalse(r.get('skipped'), r)
        real = SalesFact.objects.get(doc_no='ФР150726/1', doc_type='Реализация')
        self.assertEqual(real.schet_no, '00БП-000500')     # номер счёта навешен
        self.assertEqual(real.month, 7)
        corr = SalesFact.objects.get(doc_no='ФР030826/K1')
        self.assertEqual(corr.month, 7)                     # перенесена в месяц отгрузки
        self.assertEqual(corr.doc_date, datetime.date(2026, 7, 15))  # и дата — отгрузки
        self.assertEqual(corr.amount, -200)

    def test_validation_rejects_non_sales_file(self):
        r = loader.load_sales_client(_wb(['abc', 'def'], ['x', 'y'], [['foo', 'bar']]),
                                     'garbage.xlsx', force=True)
        self.assertTrue(r.get('skipped'))
        self.assertEqual(SalesFact.objects.count(), 0)      # данные не тронуты

    def test_partial_reload_keeps_other_months(self):
        july = [['Реализация (акт, накладная, УПД) № ФР010726/1 от 01.07.2026',
                 datetime.datetime(2026, 7, 1), 'B', 'M', 5, 500, None, None],
                ['Счет покупателю 00БП-1 от 01.07.2026', None, None, None, 5, 500, None, None]]
        loader.load_sales_client(_wb(HEADER, SUB, july), 'jul.xlsx', force=True)
        aug_h = ['Документ', 'Дата', 'Контрагент', 'Менеджер', 'авг. 26', '']
        aug_s = ['Документ.Основание', '', '', '', 'Количество', 'Сумма']
        aug = [['Реализация (акт, накладная, УПД) № ФР050826/1 от 05.08.2026',
                datetime.datetime(2026, 8, 5), 'B', 'M', 3, 300]]
        loader.load_sales_client(_wb(aug_h, aug_s, aug), 'aug.xlsx', force=True)
        # июльская реализация НЕ должна пропасть при загрузке августовского файла
        self.assertTrue(SalesFact.objects.filter(doc_no='ФР010726/1').exists())
        self.assertTrue(SalesFact.objects.filter(doc_no='ФР050826/1').exists())

    def test_month_from_number_when_basis_not_in_file(self):
        # корректировка с основанием, которого нет в файле — месяц берём из номера ФРддммгг
        data = [
            ['Корректировка реализации № ФР050826/K9 от 05.08.2026',
             datetime.datetime(2026, 8, 5), 'КЛИЕНТ Х', 'М', None, None, -1, -50],
            [None, None, None, None, None, None, -1, -50],
            ['Реализация (акт, накладная, УПД) ФР200726/3 от 20.07.2026',
             None, None, None, None, None, -1, -50],
        ]
        loader.load_sales_client(_wb(HEADER, SUB, data), 'x.xlsx', force=True)
        corr = SalesFact.objects.get(doc_no='ФР050826/K9')
        self.assertEqual(corr.month, 7)                     # 20.07 → июль, из номера основания
