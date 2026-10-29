"""Replace only the successfully fetched interval; retain every other period."""
import hashlib
import json
import datetime as dt
from decimal import Decimal
from pathlib import Path

def row_date(provider,row):return str(row.get('Date' if provider=='rosneft' else 'dateRec',''))[:10]
def read(data_dir,provider):
    p=Path(data_dir)/(provider+'-history.json')
    if p.exists():return json.loads(p.read_text())
    p=Path(data_dir)/(provider+'-transactions.json')
    return json.loads(p.read_text()) if p.exists() else {'provider':provider,'rows':[],'periods':[]}

def snapshot_for_period(data_dir,provider,start,end):
    """Read saved operations without syncing or replacing another month's view.

    `periods` lists all known successful fetch intervals. Completeness refers to
    their union over the requested dates, including successful empty days.
    Freshness is the oldest of each day's latest known fetch timestamps; it is
    unknown if any requested day has no coverage or no dated successful fetch.
    Cards are current provider metadata, not a historical vehicle assignment.
    """
    if provider not in ('neftm','rosneft'):
        raise ValueError('Неизвестный топливный источник.')
    try:
        a,b=dt.date.fromisoformat(start),dt.date.fromisoformat(end)
        if a.isoformat()!=start or b.isoformat()!=end or not 0<=(b-a).days<=30:
            raise ValueError()
    except (ValueError,TypeError):
        raise ValueError('Укажите даты в формате ГГГГ-ММ-ДД и период от 1 до 31 дня.') from None
    history=read(data_dir,provider)
    periods=history.get('periods',[])
    if not periods and history.get('from') and history.get('to'):
        periods=[{'from':history['from'],'to':history['to'],'synced_at':history.get('synced_at')}]
    valid=[]
    for p in periods:
        try:
            first,last=dt.date.fromisoformat(p['from']),dt.date.fromisoformat(p['to'])
            if first>last or first.isoformat()!=p['from'] or last.isoformat()!=p['to']:continue
        except (ValueError,TypeError,KeyError):
            continue
        valid.append({'from':p['from'],'to':p['to'],'synced_at':p.get('synced_at')})
    valid.sort(key=lambda p:(p['from'],p['to']))
    day_times=[];complete=True
    for offset in range((b-a).days+1):
        day=(a+dt.timedelta(days=offset)).isoformat()
        covering=[p for p in valid if p['from']<=day<=p['to']]
        complete=complete and bool(covering)
        dated=[]
        for p in covering:
            try:
                stamp=dt.datetime.fromisoformat(p['synced_at'])
                if stamp.tzinfo is not None:dated.append((stamp,p['synced_at']))
            except (ValueError,TypeError):
                pass
        day_times.append(max(dated,key=lambda pair:pair[0]) if dated else None)
    synced_at=min(day_times,key=lambda pair:pair[0])[1] if complete and all(day_times) else None
    rows=[r for r in history.get('rows',[]) if start<=row_date(provider,r)<=end]
    date_field='Date' if provider=='rosneft' else 'dateRec'
    rows.sort(key=lambda row:str(row.get(date_field,'')),reverse=True)
    return dict(provider=provider,**{'from':start,'to':end},rows=rows,
                cards=history.get('cards',[]),periods=valid,complete=complete,synced_at=synced_at,
                cards_synced_at=history.get('synced_at') if history.get('cards') else None)

def persist(data_dir,result):
    from app.neftm import write_json
    provider=result['provider'];old=read(data_dir,provider)
    a,b=result['from'],result['to']
    rows=[r for r in old.get('rows',[]) if not a<=row_date(provider,r)<=b]
    if provider=='rosneft':
        ids={(r.get('Contract'),r['Code']) for r in result['rows']}
        rows=[r for r in rows if (r.get('Contract'),r['Code']) not in ids]
    rows+=result['rows']
    periods=old.get('periods',[])
    if not periods and old.get('from'):periods=[{'from':old['from'],'to':old['to'],'synced_at':old.get('synced_at')}]
    periods=[p for p in periods if not (a<=p['from'] and p['to']<=b)]+[{'from':a,'to':b,'synced_at':result['synced_at']}]
    body=dict(result,rows=rows,periods=periods)
    write_json(Path(data_dir)/(provider+'-history.json'),body)

def normalized(data_dir):
    out=[];periods={}
    for provider in ('neftm','rosneft'):
        history=read(data_dir,provider);periods[provider]=history.get('periods',[])
        if not periods[provider] and history.get('from'):periods[provider]=[{'from':history['from'],'to':history['to']}]
        for i,r in enumerate(history.get('rows',[])):
            if provider=='rosneft':
                known=r['Type'] in (11,24);sign=-1 if r['Type']==24 else 1
                amount=float(Decimal(r['NetSum'])*sign) if known else None
                liters=float(Decimal(r['Value'])*sign) if known and r.get('GCat')=='FUEL' else None
                card=r['Card'];name=r.get('GName','');ident=r['Code'];operation=str(r['Type'])
            else:
                # PWS servicing (11) and refunds (24); other movements are not purchases.
                known=r.get('typeNumber') in ('11','24') and r.get('currencyName')=='Рубли'
                sign=-1 if r.get('typeNumber')=='24' else 1
                amount=float(Decimal(r['costClient'])*sign) if known else None
                name=r.get('serviceName','');card=r.get('cardNumber','');operation=r.get('typeNumber','')
                liters=float(Decimal(r['amount'])*sign) if known and any(x in name.casefold() for x in ('дт','диз','аи-','бенз','газ')) else None
                ident=hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest()[:16]+':'+str(i)
            out.append(dict(id=provider+':'+ident,provider=provider,date=row_date(provider,r),card=card,product=name,amount=amount,liters=liters,operation=operation))
    return out,periods
