"""Small generated workbooks: no customer source files are needed by API tests."""
import datetime as dt
from pathlib import Path
from openpyxl import Workbook


def books(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    sw=Workbook();sw.remove(sw.active)
    for name in ('ТрансТрейд','Спутник','Блокнот','Справочник'):sw.create_sheet(name)
    sw['Справочник'].append(['Авто','Марка',None,'Водитель',None,'Причина',None,None,None,'Объект','Номер'])
    sw['Справочник'].append(['Т711РМ797','Марка А',None,'Фаллахи Динислам Сергеевич',None,'Сервис',None,None,None,'Тестовый объект','Т711РМ797'])
    sw['Справочник'].append(['У930ЕХ797','Марка Б',None,'Тестовый водитель',None,'Ремонт',None,None,None,None,None])
    sw['ТрансТрейд'].append(['Тестовая книга'])
    sw['ТрансТрейд'].append(['Номер','Начало','Конец','Клиент','Исполнитель','Водитель','Тип','Авто','Выручка','Оплата','Выплата','Оплата исполнителю','Км'])
    start=dt.datetime(2026,8,1,8)
    for ident,kind,revenue,payout,km,h in [(1,'1.5 тонны',1000,400,100,4),(2,'1.5 тонны',2000,700,200,27),(3,'доплата',300,100,0,0),(4,'штраф водителю',-100,-100,0,0)]:
        sw['ТрансТрейд'].append([ident,start,start+dt.timedelta(hours=h),'Тестовый клиент','Тестовый исполнитель','Фаллахи Динислам Сергеевич',kind,'Т711РМ797',revenue,'Безнал',payout,'Нал',km])
    sw['Спутник'].append(['id','Объект','Начало','Конец','Длительность','Км','Счетчик начало','Счетчик конец','Моточасы','Движение','Остановка','Холостой ход','Откуда','Куда'])
    sw['Спутник'].append([1,'Тестовый объект',start,start+dt.timedelta(hours=24),1,310,0,310,0.25,0.2,0.75,0.05,'Тест','Тест'])
    for _ in range(7):sw['Блокнот'].append(['Дата','Автомобиль','Статус','Водитель','Статус водителя'])
    sw['Блокнот'].append([dt.datetime(2026,8,2),'Т711РМ797','Сервис',None,None])
    pw=Workbook();pw.remove(pw.active)
    for name in ('Логист','Маршруты Почта','Водители','Автомобили'):pw.create_sheet(name)
    pw['Водители'].append(['Водитель','Компания']);pw['Водители'].append(['Фаллахи Динислам Сергеевич','Тестовая компания'])
    pw['Автомобили'].append(['Авто','Компания']);pw['Автомобили'].append(['Т711РМ797','Тестовая компания'])
    pw['Маршруты Почта'].append(['Компания','Маршрут','Выручка','Выплата','Партнер','Км','Часы','Ставка','Партнер ставка'])
    pw['Маршруты Почта'].append(['Тест','Тестовый маршрут',1000,400,600,100,4/24,250,150])
    for _ in range(6):pw['Логист'].append(['Заголовок'])
    pw['Логист'].append([dt.datetime(2026,7,1),None,'Фаллахи Динислам Сергеевич','Т711РМ797','Тестовый маршрут',None])
    paths=(folder/'statistics.xlsx',folder/'planner.xlsx')
    sw.save(paths[0]);pw.save(paths[1]);sw.close();pw.close()
    return paths
