"""Replace only the successfully fetched interval; retain every other period."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

def row_date(provider,row):return str(row.get('Date' if provider=='rosneft' else 'dateRec',''))[:10]
def read(data_dir,provider):
    p=Path(data_dir)/(provider+'-history.json')
    if p.exists():return json.loads(p.read_text())
    p=Path(data_dir)/(provider+'-transactions.json')
    return json.loads(p.read_text()) if p.exists() else {'provider':provider,'rows':[],'periods':[]}

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
