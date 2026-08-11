import base64
import io
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st
from PIL import Image

from src.clipboard_component import clipboard_image_paste
from src.db import add_bet, database_mode, database_source, delete_bet, get_bets, get_users, init_db, update_result, update_bet
from src.parser import image_to_text, parse_text
from src.api_football import api_enabled, enrich_from_api, suggest_settlement
from src.reports import group_report, kpis, prepare

st.set_page_config(page_title='BetManager Cloud', page_icon='📊', layout='wide')
init_db()

st.markdown('''
<style>
/* Dashboard Pro visual */
[data-testid="stAppViewContainer"] { background: #0b1017; }
[data-testid="stSidebar"] { background: #0d141d; border-right: 1px solid rgba(255,255,255,.07); }
.block-container { max-width: 1500px; padding-top: 1.4rem; padding-bottom: 3rem; }

div[data-testid="stMetric"] {
    background: linear-gradient(145deg, rgba(20,29,40,.98), rgba(13,20,29,.98));
    border: 1px solid rgba(255,255,255,.08);
    padding: 15px 16px;
    border-radius: 13px;
    min-height: 112px;
    box-shadow: 0 8px 22px rgba(0,0,0,.14);
}
div[data-testid="stMetric"] label { font-size: .78rem !important; text-transform: uppercase; letter-spacing: .035em; opacity:.78; }
div[data-testid="stMetricValue"] { font-weight: 750; }

[data-testid="stDataFrame"] {
    border: 1px solid rgba(255,255,255,.08);
    border-radius: 12px;
    overflow: hidden;
}
[data-testid="stPlotlyChart"] {
    background: #101821;
    border: 1px solid rgba(255,255,255,.08);
    border-radius: 14px;
    padding: 8px;
}
h3 { margin-top: 1.2rem !important; }
hr { border-color: rgba(255,255,255,.08) !important; }
</style>
''', unsafe_allow_html=True)

st.markdown('''
<style>
.block-container {padding-top:1.3rem;max-width:1500px}
[data-testid="stMetric"] {border:1px solid rgba(120,120,120,.18);padding:14px;border-radius:14px}
</style>
''', unsafe_allow_html=True)

st.title('📊 BetManager Professional')
st.caption('Ctrl+V • unidades (U) • HALF WIN/LOSS • filtros profissionais • multiusuário • todos ADMIN')

if 'user_name' not in st.session_state:
    st.session_state.user_name = 'Jonata'

with st.sidebar:
    st.header('Acesso ADMIN')
    st.session_state.user_name = st.text_input('Apostador atual', value=st.session_state.user_name).strip() or 'Usuário'
    users = get_users()
    if st.session_state.user_name not in users:
        users = sorted(users + [st.session_state.user_name])
    selected_view = st.selectbox('Visualizar dados de', ['TODOS'] + users, format_func=lambda x: 'Todos os apostadores' if x == 'TODOS' else x)
    page = st.radio('Menu', ['Dashboard','Importar aposta','Apostas','Liquidação','Relatórios','Exportar'])
    st.divider()
    st.caption('Perfil: ADMIN • acesso total')
    st.caption(f'Banco: {database_mode()} • origem: {database_source()}')


def data_for_view():
    return get_bets(None if selected_view == 'TODOS' else selected_view)


def image_from_data_url(data_url: str):
    raw = data_url.split(',', 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(raw))).convert('RGB')


BOOKMAKER_OPTIONS = ['Betano','Bet365','Bolsa','Pinnacle','Outra']

def bookmaker_index(value):
    value=(value or '').strip().lower()
    aliases={
        'betano':'Betano','bet365':'Bet365','bet 365':'Bet365',
        'bolsa':'Bolsa','betfair':'Bolsa','exchange':'Bolsa',
        'pinnacle':'Pinnacle','pinacle':'Pinnacle'
    }
    normalized=aliases.get(value,'Outra')
    return BOOKMAKER_OPTIONS.index(normalized)



if page == 'Dashboard':
    df = data_for_view()
    stats = kpis(df)
    scope = 'Todos os apostadores' if selected_view == 'TODOS' else selected_view
    st.subheader(f'Dashboard — {scope}')

    k1,k2,k3,k4,k5,k6 = st.columns(6)
    k1.metric('Lucro', f"{stats['profit_units']:+.2f}u")
    k2.metric('ROI / Yield', f"{stats['roi']:.2f}%")
    k3.metric('Apostas', stats['bets'])
    k4.metric('Unidades apostadas', f"{stats['units']:.2f}u")
    k5.metric('Taxa de acerto', f"{stats['hit_rate']:.1f}%")
    k6.metric('Odd média', f"{stats['avg_odds']:.2f}")

    k1,k2,k3,k4 = st.columns(4)
    k1.metric('Drawdown máx.', f"{stats['drawdown']:.2f}u")
    k2.metric('Pendentes', stats.get('pending', int((df['result']=='PENDENTE').sum()) if not df.empty else 0))
    k3.metric('Melhor sequência', str(stats.get('best_streak',0)))
    k4.metric('Pior sequência', str(stats.get('worst_streak',0)))

    d = prepare(df)
    if d.empty:
        st.info('Ainda não há apostas cadastradas.')
    else:
        settled = d[d['result'].isin(['WIN','HALF WIN','VOID','HALF LOSS','LOSS'])].copy().sort_values(['bet_date','id'])

        st.markdown('### Evolução')
        c1,c2 = st.columns([1.7,1])
        with c1:
            if not settled.empty:
                settled['lucro_acumulado_u'] = settled['profit_units'].cumsum()
                st.plotly_chart(px.area(settled,x='bet_date',y='lucro_acumulado_u',markers=True,title='Evolução do Lucro (U)'),use_container_width=True)
            else:
                st.info('Sem apostas liquidadas para montar a curva de lucro.')
        with c2:
            if not settled.empty:
                result_order=['WIN','HALF WIN','VOID','HALF LOSS','LOSS']
                rc=settled['result'].value_counts().reindex(result_order,fill_value=0).reset_index()
                rc.columns=['Resultado','Quantidade']
                st.plotly_chart(px.bar(rc,x='Resultado',y='Quantidade',title='Distribuição de resultados'),use_container_width=True)

        st.markdown('### Onde está o resultado')
        c1,c2 = st.columns(2)
        with c1:
            mr = group_report(df,'market')
            st.markdown('#### Mercados')
            if not mr.empty:
                st.dataframe(mr[['market','apostas','unidades','lucro_u','roi_%','odd_media']].head(8),hide_index=True,use_container_width=True)
        with c2:
            cr = group_report(df,'competition')
            st.markdown('#### Campeonatos')
            if not cr.empty:
                st.dataframe(cr[['competition','apostas','unidades','lucro_u','roi_%','odd_media']].head(8),hide_index=True,use_container_width=True)

        c1,c2 = st.columns(2)
        with c1:
            orp = group_report(df,'odd_band')
            st.markdown('#### Faixas de odd')
            if not orp.empty:
                st.dataframe(orp[['odd_band','apostas','lucro_u','roi_%','odd_media']].head(8),hide_index=True,use_container_width=True)
        with c2:
            tr = group_report(df,'timing')
            st.markdown('#### Pré-jogo x Ao vivo')
            if not tr.empty:
                st.dataframe(tr[['timing','apostas','lucro_u','roi_%','odd_media']],hide_index=True,use_container_width=True)

        st.markdown('### Insights rápidos')
        insights=[]
        if not settled.empty:
            if stats['roi'] > 0:
                insights.append(f"🟢 ROI geral positivo em **{stats['roi']:.2f}%**.")
            elif stats['roi'] < 0:
                insights.append(f"🔴 ROI geral negativo em **{stats['roi']:.2f}%**.")
            if stats['drawdown'] < 0:
                insights.append(f"⚠️ Drawdown máximo de **{stats['drawdown']:.2f}u**.")
            if not mr.empty:
                best=mr.iloc[0]
                worst=mr.sort_values('lucro_u').iloc[0]
                insights.append(f"🔥 Melhor mercado: **{best['market']}** ({best['lucro_u']:+.2f}u | ROI {best['roi_%']:.2f}%).")
                if worst['lucro_u'] < 0:
                    insights.append(f"📉 Mercado com maior perda: **{worst['market']}** ({worst['lucro_u']:+.2f}u | ROI {worst['roi_%']:.2f}%).")
            if not cr.empty:
                bestc=cr.iloc[0]
                insights.append(f"🏆 Melhor campeonato: **{bestc['competition']}** ({bestc['lucro_u']:+.2f}u).")
            if not settled.empty:
                _daily = settled.copy()
                _daily['_dia'] = pd.to_datetime(_daily['bet_date'], errors='coerce').dt.date
                _daily = _daily.groupby('_dia', as_index=False)['profit_units'].sum()
                if not _daily.empty:
                    _bestday = _daily.loc[_daily['profit_units'].idxmax()]
                    _worstday = _daily.loc[_daily['profit_units'].idxmin()]
                    insights.append(f"📈 Melhor dia: **{_bestday['_dia']}** ({_bestday['profit_units']:+.2f}u).")
                    if _worstday['profit_units'] < 0:
                        insights.append(f"📉 Pior dia: **{_worstday['_dia']}** ({_worstday['profit_units']:+.2f}u).")
            pend = int((d['result']=='PENDENTE').sum())
            if pend:
                insights.append(f"⏳ Existem **{pend} apostas pendentes** para liquidar.")
        if insights:
            for item in insights[:6]:
                st.markdown(item)
        else:
            st.caption('Os insights aparecerão conforme as apostas forem sendo liquidadas.')

        if selected_view == 'TODOS':
            ur = group_report(df,'user_name')
            if not ur.empty:
                st.markdown('### Ranking por apostador')
                st.dataframe(ur[['user_name','apostas','unidades','lucro_u','roi_%','odd_media']],hide_index=True,use_container_width=True)

elif page == 'Importar aposta':
    st.info(f'Aposta vinculada a **{st.session_state.user_name}**. O valor em R$ do bilhete não é usado no desempenho: o padrão é **1u**.')
    st.subheader('Cole o print ou envie a imagem')
    st.caption('Assim que a imagem for recebida, o BetManager faz a leitura automaticamente e abre a ficha para conferência.')

    pasted = clipboard_image_paste(key='paste_bet')
    uploaded = st.file_uploader('Alternativa: enviar arquivo', type=['png','jpg','jpeg','webp'])

    image = None
    image_token = None
    if pasted and isinstance(pasted, dict) and pasted.get('data_url'):
        try:
            image = image_from_data_url(pasted['data_url'])
            image_token = f"paste:{pasted.get('ts', len(pasted.get('data_url','')))}"
            st.session_state.current_bet_image = pasted['data_url']
        except Exception:
            st.error('Não consegui abrir a imagem colada.')
    elif uploaded:
        raw = uploaded.getvalue()
        image = Image.open(io.BytesIO(raw)).convert('RGB')
        image_token = f"upload:{uploaded.name}:{len(raw)}:{hash(raw)}"
        st.session_state.current_bet_image = 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')

    # OCR automático: executa somente uma vez para cada imagem nova.
    if image is not None and image_token and st.session_state.get('last_image_token') != image_token:
        try:
            with st.spinner('Lendo o bilhete automaticamente...'):
                ocr_text = image_to_text(image)
                parsed = parse_text(ocr_text)
                parsed['user_name'] = st.session_state.user_name
                if api_enabled():
                    parsed = enrich_from_api(parsed)
                st.session_state.ocr_text = ocr_text
                st.session_state.parsed_bet = parsed
                st.session_state.last_image_token = image_token
                st.session_state.read_error = ''
        except Exception as exc:
            st.session_state.read_error = str(exc)
            st.session_state.last_image_token = image_token

    if st.session_state.get('read_error'):
        st.error(st.session_state.read_error)

    if 'parsed_bet' in st.session_state:
        p = st.session_state.parsed_bet
        left, right = st.columns([0.85, 1.6], gap='large')
        with left:
            st.markdown('#### Print recebido')
            preview = None
            if st.session_state.get('current_bet_image'):
                try:
                    preview = image_from_data_url(st.session_state.current_bet_image)
                except Exception:
                    preview = image
            if preview is not None:
                st.image(preview, use_container_width=True)
            with st.expander('Ver texto lido pelo OCR'):
                st.text_area('Texto extraído', value=st.session_state.get('ocr_text',''), height=180, disabled=True, label_visibility='collapsed')

        with right:
            st.markdown('#### Confira e ajuste')
            st.caption('Tudo abaixo pode ser corrigido antes de salvar.')
            if p.get('_api_status'):
                if p.get('_api_fixture_id'):
                    st.success(f"⚽ {p.get('_api_status')} • campeonato preenchido automaticamente.")
                else:
                    st.caption(f"API-Football: {p.get('_api_status')}")
            with st.form('bet_form', clear_on_submit=False):
                a,b,c=st.columns(3)
                bettor=a.text_input('Apostador', value=st.session_state.user_name)
                bet_date=b.date_input('Data', value=pd.to_datetime(p.get('bet_date')).date() if p.get('bet_date') else date.today())
                bookmaker=c.selectbox('Casa', BOOKMAKER_OPTIONS, index=bookmaker_index(p.get('bookmaker','')))
                competition=st.text_input('Campeonato', value=p.get('competition',''))
                event=st.text_input('Evento / jogo', value=p.get('event',''))
                a,b=st.columns(2)
                market=a.text_input('Mercado', value=p.get('market',''))
                selection=b.text_input('Seleção', value=p.get('selection',''))
                a,b,c,d=st.columns(4)
                types=['Simples','Dupla','Tripla','Múltipla']
                current_type=p.get('bet_type','Simples') if p.get('bet_type') in types else 'Simples'
                bet_type=a.selectbox('Tipo', types, index=types.index(current_type))
                moments=['Pré-jogo','Ao vivo']
                current_timing=p.get('timing','Pré-jogo') if p.get('timing') in moments else 'Pré-jogo'
                timing=b.selectbox('Momento',moments,index=moments.index(current_timing))
                odds=c.number_input('Odd',min_value=1.0,value=float(p.get('odds',1.0)),step=0.01)
                units=d.number_input('Unidades (u)',min_value=0.05,value=float(p.get('units',1.0)),step=0.25,help='Padrão 1u. O valor em reais do print não entra no ROI.')
                a,b=st.columns(2)
                result=a.selectbox('Resultado',['PENDENTE','WIN','HALF WIN','VOID','HALF LOSS','LOSS'])
                source_money=b.number_input('Valor em R$ do print (informativo)',min_value=0.0,value=float(p.get('source_stake_money',0.0)),step=1.0,disabled=True)
                notes=st.text_area('Observações')
                save=st.form_submit_button('💾 Salvar aposta',type='primary',use_container_width=True)
                if save:
                    profit = units*(odds-1) if result=='WIN' else units*(odds-1)/2 if result=='HALF WIN' else -units/2 if result=='HALF LOSS' else -units if result=='LOSS' else 0.0
                    data=dict(p); data.update({
                        'user_name':bettor.strip() or st.session_state.user_name,'bet_date':str(bet_date),'bookmaker':bookmaker,'competition':competition,
                        'event':event or 'Evento não informado','market':market,'selection':selection,'bet_type':bet_type,'timing':timing,
                        'odds':odds,'units':units,'source_stake_money':source_money,'result':result,'profit_units':profit,'notes':notes,
                        'source_text':st.session_state.get('ocr_text','')
                    })
                    add_bet(data)
                    st.success(f'Aposta salva: {units:.2f}u para {data["user_name"]}.')
                    for key in ['parsed_bet','ocr_text','current_bet_image','last_image_token','read_error']:
                        st.session_state.pop(key, None)
    elif image is None:
        st.caption('Cole uma imagem na área acima com Ctrl+V ou envie um arquivo para abrir a ficha automaticamente.')

elif page == 'Apostas':
    st.subheader('Histórico — todos ADMIN')
    df=data_for_view()
    if df.empty:
        st.info('Nenhuma aposta cadastrada.')
    else:
        st.caption('Filtros rápidos')
        f1,f2,f3,f4=st.columns(4)
        q=f1.text_input('Buscar jogo/seleção')
        res=f2.multiselect('Resultado', ['PENDENTE','WIN','HALF WIN','VOID','HALF LOSS','LOSS'])
        markets=f3.multiselect('Mercado', sorted([x for x in df['market'].dropna().unique() if str(x).strip()]))
        books=f4.multiselect('Casa', sorted([x for x in df['bookmaker'].dropna().unique() if str(x).strip()]))
        view=df.copy()
        if q:
            mask=view[['event','selection','competition']].fillna('').astype(str).apply(lambda c:c.str.contains(q,case=False,regex=False)).any(axis=1); view=view[mask]
        if res: view=view[view['result'].isin(res)]
        if markets: view=view[view['market'].isin(markets)]
        if books: view=view[view['bookmaker'].isin(books)]
        cols=['id','user_name','bet_date','bookmaker','competition','event','market','selection','odds','units','result','profit_units']
        st.dataframe(view[cols],hide_index=True,use_container_width=True)
        if view.empty: st.warning('Nenhuma aposta encontrada com esses filtros.')
        else:
            c1,c2,c3=st.columns([1,1,2]); bet_id=c1.selectbox('Aposta #',view['id'].tolist()); result=c2.selectbox('Resultado',['WIN','HALF WIN','VOID','HALF LOSS','LOSS','PENDENTE'])
            if c3.button('Atualizar resultado',use_container_width=True):
                update_result(int(bet_id),result); st.success('Resultado atualizado.'); st.rerun()
            row=df[df['id']==bet_id].iloc[0]
            with st.expander('✏️ Editar aposta selecionada'):
                with st.form('edit_bet'):
                    e1,e2,e3=st.columns(3)
                    eu=e1.text_input('Apostador',str(row.user_name)); ed=e2.date_input('Data',pd.to_datetime(row.bet_date).date()); eb=e3.selectbox('Casa',BOOKMAKER_OPTIONS,index=bookmaker_index(str(row.bookmaker or '')))
                    ec=st.text_input('Campeonato',str(row.competition or '')); ee=st.text_input('Evento',str(row.event))
                    e1,e2=st.columns(2); em=e1.text_input('Mercado',str(row.market or '')); es=e2.text_input('Seleção',str(row.selection or ''))
                    e1,e2,e3,e4=st.columns(4)
                    et=e1.selectbox('Tipo',['Simples','Dupla','Tripla','Múltipla'],index=['Simples','Dupla','Tripla','Múltipla'].index(row.bet_type) if row.bet_type in ['Simples','Dupla','Tripla','Múltipla'] else 0)
                    eti=e2.selectbox('Momento',['Pré-jogo','Ao vivo'],index=1 if row.timing=='Ao vivo' else 0)
                    eo=e3.number_input('Odd',min_value=1.0,value=float(row.odds),step=.01); eun=e4.number_input('Unidades',min_value=.05,value=float(row.units),step=.25)
                    en=st.text_area('Observações',str(row.notes or ''))
                    if st.form_submit_button('Salvar alterações',use_container_width=True):
                        update_bet(int(bet_id),{'user_name':eu,'bet_date':str(ed),'bookmaker':eb,'competition':ec,'event':ee,'market':em,'selection':es,'bet_type':et,'timing':eti,'odds':eo,'units':eun,'notes':en})
                        st.success('Aposta atualizada.'); st.rerun()
            if st.button('🗑️ Excluir aposta selecionada'):
                delete_bet(int(bet_id)); st.success('Aposta excluída.'); st.rerun()

elif page == 'Liquidação':
    st.subheader('Liquidação e pendências')
    df=data_for_view()
    pending=df[df['result'].eq('PENDENTE')].copy() if not df.empty else pd.DataFrame()

    if pending.empty:
        st.success('Não há apostas pendentes neste filtro.')
    else:
        st.caption('A API pode sugerir o resultado. Você confirma antes de gravar.')
        f1,f2,f3=st.columns(3)
        q=f1.text_input('Buscar jogo',key='liq_q')
        markets=f2.multiselect('Mercado',sorted([x for x in pending['market'].dropna().unique() if str(x).strip()]),key='liq_market')
        bettors=f3.multiselect('Apostador',sorted([x for x in pending['user_name'].dropna().unique() if str(x).strip()]),key='liq_user')

        view=pending.copy()
        if q:
            view=view[view['event'].fillna('').str.contains(q,case=False,regex=False)]
        if markets:
            view=view[view['market'].isin(markets)]
        if bettors:
            view=view[view['user_name'].isin(bettors)]

        st.dataframe(
            view[['id','bet_date','user_name','event','market','selection','odds','units']],
            hide_index=True,use_container_width=True
        )

        if not view.empty:
            bet_id=st.selectbox('Selecione a aposta pendente',view['id'].tolist(),key='liq_bet')
            row=view[view['id']==bet_id].iloc[0].to_dict()

            c1,c2=st.columns([1,1])
            with c1:
                st.markdown(f"**{row['event']}**")
                st.caption(f"{row.get('market','')} • {row.get('selection','')} • Odd {float(row.get('odds',1)):.2f} • {float(row.get('units',1)):.2f}u")
                if st.button('🤖 Sugerir resultado pela API',use_container_width=True):
                    with st.spinner('Consultando resultado e estatísticas...'):
                        st.session_state['settlement_suggestion']=suggest_settlement(row)
                        st.session_state['settlement_bet_id']=int(bet_id)

            with c2:
                sug=st.session_state.get('settlement_suggestion') if st.session_state.get('settlement_bet_id')==int(bet_id) else None
                if sug:
                    if sug.get('suggestion'):
                        st.success(f"Sugestão: **{sug['suggestion']}**")
                        if sug.get('detail'):
                            st.caption(sug['detail'])
                    else:
                        st.warning(sug.get('status','Não foi possível sugerir.'))

            options=['WIN','HALF WIN','VOID','HALF LOSS','LOSS','PENDENTE']
            default='PENDENTE'
            if sug and sug.get('suggestion') in options:
                default=sug['suggestion']
            chosen=st.selectbox('Resultado a confirmar',options,index=options.index(default),key=f'liq_result_{bet_id}')
            if st.button('✅ Confirmar liquidação',type='primary',use_container_width=True):
                if chosen=='PENDENTE':
                    st.warning('Escolha um resultado antes de confirmar.')
                else:
                    update_result(int(bet_id),chosen)
                    st.success(f'Aposta #{bet_id} liquidada como {chosen}.')
                    st.session_state.pop('settlement_suggestion',None)
                    st.session_state.pop('settlement_bet_id',None)
                    st.rerun()

elif page == 'Relatórios':
    st.subheader('Relatórios Pro')
    df=data_for_view()
    d=prepare(df)

    if d.empty:
        st.info('Sem dados para analisar.')
    else:
        st.caption('Cruze período, apostador, campeonato, mercado, casa, faixa de odd, momento e resultado.')

        # Filtros
        f1,f2,f3,f4=st.columns(4)
        dates=pd.to_datetime(d['bet_date'],errors='coerce').dt.date
        min_date=dates.min()
        max_date=dates.max()
        period=f1.date_input('Período',value=(min_date,max_date),min_value=min_date,max_value=max_date)
        users=f2.multiselect('Apostador',sorted(d['user_name'].dropna().astype(str).unique().tolist()))
        markets=f3.multiselect('Mercado',sorted(d['market'].dropna().astype(str).unique().tolist()))
        comps=f4.multiselect('Campeonato',sorted(d['competition'].dropna().astype(str).unique().tolist()))

        f1,f2,f3,f4=st.columns(4)
        books=f1.multiselect('Casa',sorted(d['bookmaker'].dropna().astype(str).unique().tolist()))
        oddbands=f2.multiselect('Faixa de odd',sorted(d['odd_band'].dropna().astype(str).unique().tolist()))
        timings=f3.multiselect('Momento',sorted(d['timing'].dropna().astype(str).unique().tolist()))
        results=f4.multiselect('Resultado',sorted(d['result'].dropna().astype(str).unique().tolist()))

        view=d.copy()
        if isinstance(period,(list,tuple)) and len(period)==2:
            vd=pd.to_datetime(view['bet_date'],errors='coerce').dt.date
            view=view[(vd>=period[0])&(vd<=period[1])]
        if users: view=view[view['user_name'].isin(users)]
        if markets: view=view[view['market'].isin(markets)]
        if comps: view=view[view['competition'].isin(comps)]
        if books: view=view[view['bookmaker'].isin(books)]
        if oddbands: view=view[view['odd_band'].isin(oddbands)]
        if timings: view=view[view['timing'].isin(timings)]
        if results: view=view[view['result'].isin(results)]

        settled=view[view['result'].isin(['WIN','HALF WIN','VOID','HALF LOSS','LOSS'])].copy()
        units=float(settled['units'].sum()) if not settled.empty else 0
        profit=float(settled['profit_units'].sum()) if not settled.empty else 0
        roi=(profit/units*100) if units else 0
        wins=float(settled['result'].map({'WIN':1,'HALF WIN':.5,'VOID':0,'HALF LOSS':0,'LOSS':0}).fillna(0).sum()) if not settled.empty else 0
        hit=(wins/len(settled)*100) if len(settled) else 0
        avg=float(settled['odds'].mean()) if not settled.empty else 0

        k1,k2,k3,k4,k5,k6=st.columns(6)
        k1.metric('Lucro',f'{profit:+.2f}u')
        k2.metric('ROI',f'{roi:.2f}%')
        k3.metric('Apostas',len(view))
        k4.metric('Liquidadas',len(settled))
        k5.metric('Acerto',f'{hit:.1f}%')
        k6.metric('Odd média',f'{avg:.2f}')

        st.markdown('### Evolução do recorte')
        if not settled.empty:
            ev=settled.sort_values(['bet_date','id']).copy()
            ev['lucro_acumulado_u']=ev['profit_units'].cumsum()
            st.plotly_chart(px.line(ev,x='bet_date',y='lucro_acumulado_u',markers=True,title='Lucro acumulado do filtro'),use_container_width=True)

        c1,c2=st.columns(2)
        with c1:
            st.markdown('### Mercados')
            rr=group_report(view,'market')
            if not rr.empty:
                st.dataframe(rr[['market','apostas','unidades','lucro_u','roi_%','odd_media']],hide_index=True,use_container_width=True)
        with c2:
            st.markdown('### Campeonatos')
            rr2=group_report(view,'competition')
            if not rr2.empty:
                st.dataframe(rr2[['competition','apostas','unidades','lucro_u','roi_%','odd_media']],hide_index=True,use_container_width=True)

        c1,c2=st.columns(2)
        with c1:
            st.markdown('### Casas')
            rb=group_report(view,'bookmaker')
            if not rb.empty:
                st.dataframe(rb[['bookmaker','apostas','lucro_u','roi_%','odd_media']],hide_index=True,use_container_width=True)
        with c2:
            st.markdown('### Faixas de odd')
            ro=group_report(view,'odd_band')
            if not ro.empty:
                st.dataframe(ro[['odd_band','apostas','lucro_u','roi_%','odd_media']],hide_index=True,use_container_width=True)

        st.markdown('### Insights do filtro')
        insights=[]
        if len(settled):
            insights.append(f"Resultado do recorte: **{profit:+.2f}u**, com ROI de **{roi:.2f}%** em **{len(settled)}** apostas liquidadas.")
            if not rr.empty:
                best=rr.iloc[0]
                worst=rr.sort_values('lucro_u').iloc[0]
                insights.append(f"Melhor mercado: **{best['market']}** ({best['lucro_u']:+.2f}u / ROI {best['roi_%']:.2f}%).")
                if worst['lucro_u']<0:
                    insights.append(f"Maior perda por mercado: **{worst['market']}** ({worst['lucro_u']:+.2f}u).")
            if not rr2.empty:
                bc=rr2.iloc[0]
                insights.append(f"Melhor campeonato: **{bc['competition']}** ({bc['lucro_u']:+.2f}u / ROI {bc['roi_%']:.2f}%).")
        for x in insights:
            st.markdown('• '+x)

        # Calendário diário
        st.markdown('### Calendário de resultados')
        if not settled.empty:
            daily=settled.copy()
            daily['dia']=pd.to_datetime(daily['bet_date'],errors='coerce').dt.date
            cal=daily.groupby('dia',as_index=False).agg(
                apostas=('id','count'),
                unidades=('units','sum'),
                lucro_u=('profit_units','sum')
            )
            cal['roi_%']=(cal['lucro_u']/cal['unidades']*100).round(2)
            cal['lucro_u']=cal['lucro_u'].round(2)
            cal['unidades']=cal['unidades'].round(2)
            cal=cal.sort_values('dia',ascending=False)
            st.dataframe(cal,hide_index=True,use_container_width=True)

            selected_day=st.selectbox('Abrir apostas do dia',cal['dia'].tolist())
            daybets=daily[daily['dia']==selected_day]
            st.dataframe(
                daybets[['bet_date','user_name','event','market','selection','odds','result','profit_units']],
                hide_index=True,use_container_width=True
            )

elif page == 'Exportar':
    df=data_for_view(); scope='todos' if selected_view=='TODOS' else selected_view
    if df.empty:
        st.info('Nenhum dado para exportar.')
    else:
        st.download_button('Baixar CSV',df.to_csv(index=False).encode('utf-8-sig'),f'BetManager_{scope}.csv','text/csv',use_container_width=True)
        bio=io.BytesIO()
        with pd.ExcelWriter(bio,engine='openpyxl') as writer:
            df.to_excel(writer,index=False,sheet_name='Apostas')
            for field,sheet in [('user_name','Por_Apostador'),('market','Por_Mercado'),('competition','Por_Campeonato'),('bookmaker','Por_Casa')]:
                r=group_report(df,field)
                if not r.empty: r.to_excel(writer,index=False,sheet_name=sheet)
        st.download_button('Baixar Excel com relatórios',bio.getvalue(),f'BetManager_{scope}.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
