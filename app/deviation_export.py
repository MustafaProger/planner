"""Render the signed-in user's current deviations table as an Excel workbook."""
import datetime as dt
import io

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font

HEADERS = ('Дата', 'Автомобиль', 'Исполнитель', 'Водитель',
           'Сигнал', 'Основание', 'Проверка', 'Комментарий')
WIDTHS = (14, 16, 26, 28, 28, 66, 18, 48)
MAX_ROWS = 100_000


def workbook(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError('Для выгрузки выберите от 1 до 100 000 отклонений.')
    book = Workbook(write_only=True)
    sheet = book.create_sheet('Отклонения')
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = f'A1:H{len(rows)+1}'
    for letter, width in zip('ABCDEFGH', WIDTHS):
        sheet.column_dimensions[letter].width = width
    # Validate before opening the worksheet stream.
    dates = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(HEADERS) or not all(
            isinstance(value, str) and len(value) <= 32767 for value in row
        ):
            raise ValueError('Не удалось прочитать строки отклонений для Excel.')
        try:
            dates.append(dt.date.fromisoformat(row[0]))
        except ValueError:
            raise ValueError('Некорректная дата отклонения.') from None

    def text(value):
        cell = WriteOnlyCell(sheet, value=ILLEGAL_CHARACTERS_RE.sub('', value))
        cell.data_type = 's'  # Preserve text, including strings that begin with "=".
        return cell

    titles = [text(value) for value in HEADERS]
    for cell in titles:
        cell.font = Font(bold=True)
    sheet.append(titles)
    for date, row in zip(dates, rows):
        first = WriteOnlyCell(sheet, value=date)
        first.number_format = 'dd.mm.yyyy'
        sheet.append([first, *(text(value) for value in row[1:])])
    result = io.BytesIO()
    book.save(result)
    result.seek(0)
    return result
