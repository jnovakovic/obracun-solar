import pandas as pd
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import streamlit as st
import numpy as np

def energy_calculation (production_data, consumption_df,sub_kWh):

    load_pv =pd.DataFrame()    
    load_pv['Load']=consumption_df['consumption_kw']
    load_pv['PV_kWh']= production_data['ac_power_kw']
    load_pv['net_kWh']=load_pv['Load'] - load_pv['PV_kWh']
    load_pv['from_Grid_kWh']=load_pv['net_kWh'].apply(lambda x: x if x>0 else 0)
    load_pv['to_Grid_kWh']=load_pv['net_kWh'].apply(lambda x: x if x<0 else 0)
   
    dates=load_pv.index
    months=dates.month.unique() 
    obracun=pd.DataFrame(index=months, columns=['Load_total_kWh','PV_total_kWh','net_total_kWh','Load_HT_kWh','PV_HT_kWh','net_HT_kWh','Load_LT_kWh','PV_LT_kWh','net_LT_kWh', ])     
    
    winter_months=[1,2,3,10,11,12]
    summer_months=[4,5,6,7,8,9]
    sub_kWh_winter=sub_kWh
    sub_kWh_summer=sub_kWh
    
    #LOAD & PV
    stanje_od_HT=0
    stanje_od_LT=0
    stanje_od_PV_HT=0
    stanje_od_PV_LT=0 

    # PREUZETA I PREDANA ENERGIJA
    stanje_od_to_Grid_HT=0
    stanje_od_to_Grid_LT=0
    stanje_od_from_Grid_HT=0
    stanje_od_from_Grid_LT=0       

    for month in months:    
        monthly_data=load_pv[load_pv.index.month<=month]    
       
        HT_hours=monthly_data.between_time('07:00','20:00').index
        LT_hours=monthly_data.between_time('21:00','06:00').index    
        
        stanje_do_HT=sum(monthly_data.loc[HT_hours,'Load'])    
        stanje_do_LT=sum(monthly_data.loc[LT_hours,'Load'])  

        stanje_do_PV_HT=sum(monthly_data.loc[HT_hours,'PV_kWh'])    
        stanje_do_PV_LT=sum(monthly_data.loc[LT_hours,'PV_kWh']) 

        stanje_do_to_Grid_HT=sum(monthly_data.loc[HT_hours,'to_Grid_kWh'])    
        stanje_do_to_Grid_LT=sum(monthly_data.loc[LT_hours,'to_Grid_kWh']) 

        stanje_do_from_Grid_HT=sum(monthly_data.loc[HT_hours,'from_Grid_kWh'])    
        stanje_do_from_Grid_LT=sum(monthly_data.loc[LT_hours,'from_Grid_kWh']) 
    
        Load_HT_kWh=round(stanje_do_HT-stanje_od_HT,2)
        Load_LT_kWh=round(stanje_do_LT-stanje_od_LT,2) 

        PV_HT_kWh=round(stanje_do_PV_HT-stanje_od_PV_HT,2)
        PV_LT_kWh=round(stanje_do_PV_LT-stanje_od_PV_LT,2)
  
        to_Grid_HT= round(stanje_do_to_Grid_HT-stanje_od_to_Grid_HT,2)  
        to_Grid_LT=round(stanje_do_to_Grid_LT-stanje_od_to_Grid_LT,2)

        from_Grid_HT=round(stanje_do_from_Grid_HT-stanje_od_from_Grid_HT,2)    
        from_Grid_LT=round(stanje_do_from_Grid_LT-stanje_od_from_Grid_LT,2)

        net_HT_kWh=from_Grid_HT+to_Grid_HT
        net_LT_kWh=from_Grid_LT+to_Grid_LT   
       
        obracun.loc[month,'to_Grid_HT_kWh']=to_Grid_HT
        obracun.loc[month,'to_Grid_LT_kWh']=to_Grid_LT      
        
        obracun.loc[month,'from_Grid_HT_kWh']=from_Grid_HT
        obracun.loc[month,'from_Grid_LT_kWh']=from_Grid_LT

        # od subvencioniranih kWh odbijaju se netirani iznosi energije!
        if (month in winter_months):
            sub_kWh_winter+=-(max(net_HT_kWh,0))
            sub_kWh_winter+=-(max(net_LT_kWh,0))
            obracun.loc[month,'Preostalo_subv_kWh']=(sub_kWh_winter)
        elif (month in summer_months):
            sub_kWh_summer+=-(max(net_HT_kWh,0))
            sub_kWh_summer+=-(max(net_LT_kWh,0))
            obracun.loc[month,'Preostalo_subv_kWh']=(sub_kWh_summer)        
            

        obracun.loc[month,'HT Stanje od']=round(stanje_od_from_Grid_HT,2)
        obracun.loc[month,'HT Stanje do']=round(stanje_do_from_Grid_HT,2)
        obracun.loc[month,'LT Stanje od']=round(stanje_od_from_Grid_LT,2)
        obracun.loc[month,'LT Stanje do']=round(stanje_do_from_Grid_LT,2)

        obracun.loc[month,'predano_HT Stanje od']=round(stanje_od_to_Grid_HT,2)
        obracun.loc[month,'predano_HT Stanje do']=round(stanje_do_to_Grid_HT,2)
        obracun.loc[month,'predano_LT Stanje od']=round(stanje_od_to_Grid_LT,2)
        obracun.loc[month,'predano_LT Stanje do']=round(stanje_do_to_Grid_LT,2)
        
        obracun.loc[month,'Load_total_kWh']=Load_HT_kWh+Load_LT_kWh
        obracun.loc[month,'Load_HT_kWh']=Load_HT_kWh
        obracun.loc[month,'Load_LT_kWh']=Load_LT_kWh 

        obracun.loc[month,'PV_total_kWh']=PV_HT_kWh+PV_LT_kWh
        obracun.loc[month,'PV_HT_kWh']=PV_HT_kWh
        obracun.loc[month,'PV_LT_kWh']=PV_LT_kWh 

        obracun.loc[month,'net_total_kWh']=net_HT_kWh+net_LT_kWh
        obracun.loc[month,'net_HT_kWh']=net_HT_kWh
        obracun.loc[month,'net_LT_kWh']=net_LT_kWh       


        # Calculate energy cost with subsidy consideration
        # od subvencioniranih kWh odbijaju se netirani iznosi energije!

        if month in [1,4] and obracun.loc[month,'Preostalo_subv_kWh']<0 :
            kwh_van_subv=(max((net_HT_kWh),0)+max((net_LT_kWh),0))-sub_kWh

        elif month==10 and obracun.loc[month,'Preostalo_subv_kWh']<0 :
            kwh_van_subv=-(obracun.loc[month,'Preostalo_subv_kWh']-min(obracun.loc[3,'Preostalo_subv_kWh'],0))           

        elif month not in [1,4,10] and obracun.loc[month,'Preostalo_subv_kWh']<0 :
            kwh_van_subv=-(obracun.loc[month,'Preostalo_subv_kWh']-min(obracun.loc[month-1,'Preostalo_subv_kWh'],0))

        else:
            kwh_van_subv=0      
        if (max((net_HT_kWh),0)+max((net_LT_kWh),0))>0:
            HT_van_subv = round(kwh_van_subv * max((net_HT_kWh),0) / (max((net_HT_kWh),0)+max((net_LT_kWh),0)))
        else:
            HT_van_subv=0        
        LT_van_subv = kwh_van_subv - HT_van_subv 

        obracun.loc[month,'HT_van_subv']=HT_van_subv
        obracun.loc[month,'LT_van_subv']=LT_van_subv     

        stanje_od_HT=stanje_do_HT
        stanje_od_LT=stanje_do_LT
        stanje_od_PV_HT=stanje_do_PV_HT
        stanje_od_PV_LT=stanje_do_PV_LT
        stanje_od_to_Grid_HT=stanje_do_to_Grid_HT
        stanje_od_to_Grid_LT=stanje_do_to_Grid_LT
        stanje_od_from_Grid_HT=stanje_do_from_Grid_HT
        stanje_od_from_Grid_LT=stanje_do_from_Grid_LT
                                           
    return obracun 

def create_invoice(net_interval, obracun,prices_df,sub_kWh, kSO): 
     
    prices_dict=prices_df.to_dict('records')[0]  

    net_interval=net_interval 
    
    lista_mjeseci=['Siječanj','Veljača','Ožujak','Travanj','Svibanj','Lipanj','Srpanj','Kolovoz','Rujan','Listopad','Studeni','Prosinac']   
    racuni = {}  # dictionary to hold DataFrames
    i=0
    for mjesec in lista_mjeseci:
        i+=1
        key = f'{mjesec}'
        racuni[key] = pd.DataFrame(columns=['Opis','Iznos EUR']) 

        # Detaljni prikaz stavki računa
        racuni[key].loc[10, 'Opis'] = ''

        racuni[key].loc[11, 'Opis'] = 'Početno i krajnje stanje očitanja brojila'

        racuni[key].loc[12, 'Opis'] = 'RVT R1'
        racuni[key].loc[12, 'Stanje od'] = obracun.loc[i, 'HT Stanje od']
        racuni[key].loc[12, 'Stanje do'] = obracun.loc[i, 'HT Stanje do']
        racuni[key].loc[12, 'Potrošak'] = round(obracun.loc[i, 'from_Grid_HT_kWh'])

        racuni[key].loc[13, 'Opis'] = 'RNT R2'
        racuni[key].loc[13, 'Stanje od'] = obracun.loc[i, 'LT Stanje od']
        racuni[key].loc[13, 'Stanje do'] = obracun.loc[i, 'LT Stanje do']
        racuni[key].loc[13, 'Potrošak'] = round(obracun.loc[i, 'from_Grid_LT_kWh'])

        racuni[key].loc[14, 'Opis'] = 'RVT R1 PR'
        racuni[key].loc[14, 'Stanje od'] = -obracun.loc[i, 'predano_HT Stanje od']
        racuni[key].loc[14, 'Stanje do'] = -obracun.loc[i, 'predano_HT Stanje do']
        racuni[key].loc[14, 'Potrošak'] = -round(obracun.loc[i, 'to_Grid_HT_kWh'])

        racuni[key].loc[15, 'Opis'] = 'RNT R2 PR'
        racuni[key].loc[15, 'Stanje od'] = -obracun.loc[i, 'predano_LT Stanje od']
        racuni[key].loc[15, 'Stanje do'] = -obracun.loc[i, 'predano_LT Stanje do']
        racuni[key].loc[15, 'Potrošak'] = -round(obracun.loc[i, 'to_Grid_LT_kWh'])

        netHT=racuni[key].loc[12, 'Potrošak'] - racuni[key].loc[14, 'Potrošak']
        netLT=racuni[key].loc[13, 'Potrošak'] - racuni[key].loc[15, 'Potrošak']

        if net_interval=='month':  
            coef_sell=0.8 
            sell_price_HT=coef_sell*prices_dict['Energy_HT']
            sell_price_LT=coef_sell*prices_dict['Energy_LT']    
        elif net_interval=='15min':       
            if (round(obracun.loc[i, 'to_Grid_HT_kWh'])+round(obracun.loc[i, 'to_Grid_LT_kWh'])) ==0:
                coeff_from_to=1
            else:
                coeff_from_to=-(round(obracun.loc[i, 'from_Grid_HT_kWh'])+round(obracun.loc[i, 'from_Grid_LT_kWh']))/(round(obracun.loc[i, 'to_Grid_HT_kWh'])+round(obracun.loc[i, 'to_Grid_LT_kWh']))
           
            avg_buy_price=(round(obracun.loc[i, 'from_Grid_HT_kWh'])*prices_dict['Energy_HT']+round(obracun.loc[i, 'from_Grid_LT_kWh'])*prices_dict['Energy_LT'])\
                            /max(1, (round(obracun.loc[i, 'from_Grid_HT_kWh'])+round(obracun.loc[i, 'from_Grid_LT_kWh'])))
                                                                         
            coef_sell=0.9*min(1,coeff_from_to)*kSO
            
            sell_price_HT=coef_sell*avg_buy_price
            sell_price_LT=coef_sell*avg_buy_price
               
         
        racuni[key].loc[16, 'Opis'] ='RVT Distribucija'
        if net_interval=='month':  
            racuni[key].loc[16, 'Količina'] =max(netHT,0)
        elif net_interval=='15min':
            racuni[key].loc[16, 'Količina'] =round(obracun.loc[i,'from_Grid_HT_kWh'])
        racuni[key].loc[16, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[16, 'Cijena EUR/kWh'] =prices_dict['Distr_HT']
        racuni[key].loc[16, 'Iznos EUR']=round(racuni[key].loc[16, 'Količina'] * racuni[key].loc[16, 'Cijena EUR/kWh'],2)
        
        racuni[key].loc[17, 'Opis'] ='RNT Distribucija'
        if net_interval=='month':
            racuni[key].loc[17, 'Količina'] =max(netLT,0)
        elif net_interval=='15min':
            racuni[key].loc[17, 'Količina'] =round(obracun.loc[i,'from_Grid_LT_kWh'])
        racuni[key].loc[17, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[17, 'Cijena EUR/kWh'] =prices_dict['Distr_LT']
        racuni[key].loc[17, 'Iznos EUR']=round(racuni[key].loc[17, 'Količina'] * racuni[key].loc[17, 'Cijena EUR/kWh'],2)

        racuni[key].loc[18, 'Opis'] ='Naknada za OMM Distribucija'
        racuni[key].loc[18, 'Količina'] =1
        racuni[key].loc[18, 'Jedinica mjere'] ='Mjesec'
        racuni[key].loc[18, 'Cijena EUR/kWh'] =prices_dict['Grid_fee']
        racuni[key].loc[18, 'Iznos EUR']=round(racuni[key].loc[18, 'Cijena EUR/kWh'] ,2)

        racuni[key].loc[19, 'Opis'] ='Distribucija Ukupno'
        racuni[key].loc[19,'Iznos EUR'] =round(racuni[key].loc[16:18,'Iznos EUR'].sum(),2)  


        racuni[key].loc[20, 'Opis'] ='RVT Prijenos'
        racuni[key].loc[20, 'Količina'] =racuni[key].loc[16, 'Količina']
        racuni[key].loc[20, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[20, 'Cijena EUR/kWh'] =prices_dict['Trans_HT']
        racuni[key].loc[20, 'Iznos EUR']=round(racuni[key].loc[20, 'Količina'] * racuni[key].loc[20, 'Cijena EUR/kWh'],2)
        
        racuni[key].loc[21, 'Opis'] ='RNT Prijenos'
        racuni[key].loc[21, 'Količina'] =racuni[key].loc[17, 'Količina']
        racuni[key].loc[21, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[21, 'Cijena EUR/kWh'] =prices_dict['Trans_LT']
        racuni[key].loc[21, 'Iznos EUR']=round(racuni[key].loc[21, 'Količina'] * racuni[key].loc[21, 'Cijena EUR/kWh'],2)

        racuni[key].loc[22, 'Opis'] ='Prijenos Ukupno'
        racuni[key].loc[22,'Iznos EUR'] =round(racuni[key].loc[20:21,'Iznos EUR'].sum(),2)   

        racuni[key].loc[23, 'Opis'] ='RVT Opskrba'
        racuni[key].loc[23, 'Količina'] =racuni[key].loc[16, 'Količina']-round(obracun.loc[i,'HT_van_subv'])
        racuni[key].loc[23, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[23, 'Cijena EUR/kWh'] =prices_dict['Energy_HT']
        racuni[key].loc[23, 'Iznos EUR']=round(racuni[key].loc[23, 'Količina']*racuni[key].loc[23, 'Cijena EUR/kWh'],2)
        
        racuni[key].loc[24, 'Opis'] ='RNT Opskrba'
        racuni[key].loc[24, 'Količina'] =racuni[key].loc[17, 'Količina']-round(obracun.loc[i,'LT_van_subv'])
        racuni[key].loc[24, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[24, 'Cijena EUR/kWh'] =prices_dict['Energy_LT']
        racuni[key].loc[24, 'Iznos EUR']=round(racuni[key].loc[24, 'Količina']*racuni[key].loc[24, 'Cijena EUR/kWh'],2)

        racuni[key].loc[25, 'Opis'] =f'RVT Opskrba >{sub_kWh} kWh'
        racuni[key].loc[25, 'Količina'] =round(obracun.loc[i,'HT_van_subv'])
        racuni[key].loc[25, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[25, 'Cijena EUR/kWh'] =round(prices_dict['Energy_HT']* (1+prices_dict['Sub_increase']),6)
        racuni[key].loc[25, 'Iznos EUR']=round(racuni[key].loc[25, 'Količina']*racuni[key].loc[25, 'Cijena EUR/kWh'] ,2)
        
        racuni[key].loc[26, 'Opis'] =f'RNT Opskrba >{sub_kWh} kWh'
        racuni[key].loc[26, 'Količina'] =round(obracun.loc[i,'LT_van_subv'])
        racuni[key].loc[26, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[26, 'Cijena EUR/kWh']  =round(prices_dict['Energy_LT']* (1+prices_dict['Sub_increase']),6)
        racuni[key].loc[26, 'Iznos EUR']=round(racuni[key].loc[26, 'Količina']*racuni[key].loc[26, 'Cijena EUR/kWh'] ,2)

        racuni[key].loc[27, 'Opis'] ='Naknada za opskrbu'
        racuni[key].loc[27, 'Količina'] =1
        racuni[key].loc[27, 'Jedinica mjere'] ='Mjesec'
        racuni[key].loc[27, 'Cijena EUR/kWh'] =prices_dict['Prod_fee']
        racuni[key].loc[27, 'Iznos EUR']=round(racuni[key].loc[27, 'Količina'] *prices_dict['Prod_fee'],2)

        racuni[key].loc[28, 'Opis'] ='Opskrba Ukupno'
        racuni[key].loc[28,'Iznos EUR'] =round(racuni[key].loc[23:27,'Iznos EUR'].sum(),2) 

        racuni[key].loc[29, 'Opis'] ='Ukupan iznos za el. energiju (opskrba i korištenje mreže)'        
        racuni[key].loc[29, 'Iznos EUR'] =round(racuni[key].loc[[19, 22, 28],'Iznos EUR'].sum(),2) 

        racuni[key].loc[30, 'Opis'] ='Naknada za poticanje proizvodnje iz obnovljivih izvora'
        racuni[key].loc[30, 'Količina'] =racuni[key].loc[17, 'Količina'] + racuni[key].loc[16, 'Količina']
        racuni[key].loc[30, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[30, 'Cijena EUR/kWh'] =prices_dict['RES']
        racuni[key].loc[30, 'Iznos EUR']=round(racuni[key].loc[30, 'Količina']*racuni[key].loc[30, 'Cijena EUR/kWh'],2)

        racuni[key].loc[31, 'Opis'] ='Solidarna naknada'
        racuni[key].loc[31, 'Količina'] =racuni[key].loc[30, 'Količina']
        racuni[key].loc[31, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[31, 'Cijena EUR/kWh'] =prices_dict['Solidarity']
        racuni[key].loc[31, 'Iznos EUR']=round(racuni[key].loc[31, 'Količina']*racuni[key].loc[31, 'Cijena EUR/kWh'],2)

        racuni[key].loc[1, 'Opis'] = 'Ukupan iznos za el. energiju (opskrba i korištenje mreže)'
        racuni[key].loc[1, 'Iznos EUR'] = racuni[key].loc[29, 'Iznos EUR']
        
        racuni[key].loc[2, 'Opis'] = 'Naknada za poticanje proizvodnje iz obnovljivih izvora'
        racuni[key].loc[2, 'Iznos EUR'] = racuni[key].loc[30, 'Iznos EUR']


        racuni[key].loc[3, 'Opis'] = 'Solidarna naknada'
        racuni[key].loc[3, 'Iznos EUR'] =racuni[key].loc[31, 'Iznos EUR']


        racuni[key].loc[4, 'Opis'] = 'Popust za solidarnu naknadu'
        racuni[key].loc[4, 'Iznos EUR'] =-racuni[key].loc[3, 'Iznos EUR']


        racuni[key].loc[5, 'Opis'] = 'Porezna osnovica'
        racuni[key].loc[5, 'Iznos EUR'] =round(racuni[key].loc[racuni[key].index < 5, 'Iznos EUR'].sum(),2)


        racuni[key].loc[6, 'Opis'] = f'PDV {prices_dict['VAT']*100} %'
        racuni[key].loc[6, 'Iznos EUR'] =round(racuni[key].loc[5, 'Iznos EUR']*prices_dict['VAT'],2)

        racuni[key].loc[7, 'Opis'] = 'UKUPAN IZNOS RAČUNA'
        racuni[key].loc[7, 'Iznos EUR'] =round(racuni[key].loc[6, 'Iznos EUR']+racuni[key].loc[5, 'Iznos EUR'],2)

                          
        racuni[key].loc[8, 'Opis'] = 'Vrijednost preuzete električne energije'
        if net_interval=='month':  
            racuni[key].loc[8, 'Iznos EUR'] =-(round(min(netHT,0)*sell_price_HT,2) + round(min(netLT,0)*sell_price_LT,2))
        elif net_interval=='15min':  
            racuni[key].loc[8, 'Iznos EUR'] =-(round(obracun.loc[i, 'to_Grid_HT_kWh']*sell_price_HT,2) + round(obracun.loc[i, 'to_Grid_LT_kWh']*sell_price_LT,2))
        
        racuni[key].loc[9, 'Opis'] = 'Ukupno za platiti'
        racuni[key].loc[9, 'Iznos EUR'] =racuni[key].loc[7, 'Iznos EUR'] - racuni[key].loc[8, 'Iznos EUR']  



        racuni[key].loc[32, 'Opis'] ='Neto višak energije VT'
        if net_interval=='month':  
            racuni[key].loc[32, 'Količina'] =-(round(min(netHT,0)))
        elif net_interval=='15min':  
            racuni[key].loc[32, 'Količina'] =-(round(obracun.loc[i, 'to_Grid_HT_kWh']))  
        racuni[key].loc[32, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[32, 'Cijena EUR/kWh'] =sell_price_HT
        racuni[key].loc[32, 'Iznos EUR']=round(racuni[key].loc[32, 'Količina']*racuni[key].loc[32, 'Cijena EUR/kWh'],2)

                

        racuni[key].loc[33, 'Opis'] ='Neto višak energije NT'
        if net_interval=='month':  
            racuni[key].loc[33, 'Količina'] =-(round(min(netLT,0)))
        elif net_interval=='15min':  
            racuni[key].loc[33, 'Količina'] =-(round(obracun.loc[i, 'to_Grid_LT_kWh']))
        racuni[key].loc[33, 'Jedinica mjere'] ='kWh'
        racuni[key].loc[33, 'Cijena EUR/kWh'] =sell_price_LT
        racuni[key].loc[33, 'Iznos EUR']=round(racuni[key].loc[33, 'Količina']*racuni[key].loc[33, 'Cijena EUR/kWh'],2)

        racuni[key] = racuni[key].sort_index()

    return racuni  

def year_total(obracun,racuni):

        lista_mjeseci=['Siječanj','Veljača','Ožujak','Travanj','Svibanj','Lipanj','Srpanj','Kolovoz','Rujan','Listopad','Studeni','Prosinac']  

        godisnja_bilanca=pd.DataFrame() 
        columns=['Load_HT_kWh','PV_HT_kWh','net_HT_kWh','from_Grid_HT_kWh','to_Grid_HT_kWh',\
                'Load_LT_kWh','PV_LT_kWh','net_LT_kWh','from_Grid_LT_kWh','to_Grid_LT_kWh',]
        for month in obracun.index:
                for column in columns:
                        godisnja_bilanca.loc[month,column]=round(obracun.loc[month,column],2)

                godisnja_bilanca.loc[month,'Total_Load_kWh']=obracun.loc[month,'Load_HT_kWh']+obracun.loc[month,'Load_LT_kWh']            
                godisnja_bilanca.loc[month,'Total_PV_kWh']=obracun.loc[month,'PV_HT_kWh']+obracun.loc[month,'PV_LT_kWh']
                godisnja_bilanca.loc[month,'Total_net_kWh']=obracun.loc[month,'net_HT_kWh']+obracun.loc[month,'net_LT_kWh']
                godisnja_bilanca.loc[month,'Total_from_Grid_kWh']=obracun.loc[month,'from_Grid_HT_kWh']+obracun.loc[month,'from_Grid_LT_kWh']
                godisnja_bilanca.loc[month,'Total_to_Grid_kWh']=obracun.loc[month,'to_Grid_HT_kWh']+obracun.loc[month,'to_Grid_LT_kWh']                 
                godisnja_bilanca.loc[month,'Sub_kWh_left']=obracun.loc[month,'Preostalo_subv_kWh'] 

                key = f'{lista_mjeseci[month-1]}'          
                godisnja_bilanca.loc[month,'Bill']=racuni[key].loc[9, 'Iznos EUR']
        for column in godisnja_bilanca.columns:        
                godisnja_bilanca.loc['Year',column]=round(godisnja_bilanca[column].sum(),2)
        
        all_df = pd.concat([racuni[month] for month in lista_mjeseci])
        columns_to_sum = ['Iznos EUR', 'Količina','Potrošak']
        existing_cols = [col for col in columns_to_sum if col in all_df.columns]
        godišnji_račun = all_df.groupby(all_df.index)[existing_cols].sum()        
        godišnji_račun['Opis'] = all_df.groupby(all_df.index)['Opis'].first()

        # Reorder columns if you want 'Opis' first
        cols = ['Opis'] + [col for col in godišnji_račun.columns if col != 'Opis']
        godišnji_račun = godišnji_račun[cols]

        #godišnji_račun['Stanje od'] = racuni['Siječanj']['Stanje od'] 
        godišnji_račun['Stanje od'] = 0.00
        godišnji_račun['Stanje do'] = racuni['Prosinac']['Stanje do']         
        godišnji_račun['Jedinica mjere'] = racuni['Siječanj']['Jedinica mjere'] 
        godišnji_račun['Cijena EUR/kWh'] = racuni['Siječanj']['Cijena EUR/kWh']  
        for i in [32,33]:
            if godišnji_račun.loc[i,'Količina'] !=0:
                godišnji_račun.loc[i,'Cijena EUR/kWh'] = godišnji_račun.loc[i,'Iznos EUR']/ godišnji_račun.loc[i,'Količina']
            else: 
                godišnji_račun.loc[i,'Cijena EUR/kWh'] = 0.00

        return godisnja_bilanca, godišnji_račun    


def izvrši_obracun(production_data, consumption_df,prices_df, sub_kWh=3000, net_interval='month', kSO=1 ):    

    obracun_energije=energy_calculation(production_data, consumption_df, sub_kWh)
    racuni=create_invoice(net_interval,obracun_energije, prices_df, sub_kWh, kSO)
    bilanca, godišnji_račun =year_total(obracun_energije, racuni)

    return obracun_energije, racuni, bilanca, godišnji_račun,



def plot_bill_style_plotly(df):
    df_bill = df[['Opis', 'Iznos EUR']].copy()
    # Format amounts: e.g., "1234.56" -> "1,234.56"; empty for NaN
    df_bill['Iznos EUR'] = df_bill['Iznos EUR'].apply(
        lambda x: f"{x:,.2f}" if pd.notnull(x) else ""
    )
    
    # Prepare lists for cells
    opis_list = df_bill['Opis'].tolist()
    iznos_list = df_bill['Iznos EUR'].tolist()
    
    # Bold rows containing 'Ukupno' in Opis with HTML tags
    for idx, opis in enumerate(opis_list):
        if isinstance(opis, str) and 'Ukupno' in opis:
            opis_list[idx] = f"<b>{opis}</b>"
            iznos_list[idx] = f"<b>{iznos_list[idx]}</b>" if iznos_list[idx] else "<b></b>"
    
    # Create figure with table
    fig = go.Figure(data=[go.Table(
        columnwidth=[2, 1],  # Relative widths: 4x for descriptions, 2x for amounts
        header=dict(
            values=[col for col in df_bill.columns],
            font=dict(size=12, family='Arial', color='white'),
            fill_color='darkblue',
            align=['left', 'right'],
            line_color='darkslategray',
            height=30
        ),
        cells=dict(
            values=[opis_list, iznos_list],
            font=dict(size=12, family='Arial', color='black'),
            fill_color='white',
            align=['left', 'right'],
            line_color='lightgray',
            height=25
        )
    )])
    
    # Layout adjustments: full width, minimal margins, no axis
    fig.update_layout(
        autosize=True,
        margin=dict(l=0, r=0, t=5, b=0),
        height=30 + len(df_bill) * 25,  # Dynamic height: header + rows
        showlegend=False,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    
    return fig


def display_bill_table(fig, df_bill):
    st.plotly_chart(fig, use_container_width=True)
    # CSS to bold the total row (assumes last row is 'Total' or final item)
    if len(df_bill) > 0 and 'Total' in df_bill['Opis'].iloc[-1]:
        st.markdown("""
        <style>
        div[data-testid="stPlotlyChart"] .plotly .js-plotly-plot .plotly .modebar,
        div[data-testid="stPlotlyChart"] .plotly table tbody tr:last-child td {
            font-weight: bold !important;
            font-family: 'Arial Black' !important;
        }
        </style>
        """, unsafe_allow_html=True)  

def plot_bill_style(df):
    df_bill = df[['Opis', 'Iznos EUR']].copy()
    #df_bill=df_bill[df_bill.index<10]
    df_bill['Iznos EUR'] = df_bill['Iznos EUR'].apply(lambda x: f"{x:,.2f}" if pd.notnull(x) else "")

    fig, ax = plt.subplots(figsize=(12, 0.03 * len(df_bill)))
    
    ax.axis('off')

    table = ax.table(
        cellText=df_bill.values,
        colLabels=df_bill.columns,
        cellLoc='left',
        loc='top',
        colWidths=[0.5, 0.25],
        edges='open'
    )
    table.auto_set_font_size(False)
    table.set_fontsize(12)
    table.scale(1, 1)
    for  i in range (2):
        cell = table[0, i]  # row i, column j
        cell.visible_edges = 'B' # Top, Bottom, Left, Right (any combination)
        cell = table[len(df_bill), i]  # row i, column j
        cell.visible_edges = 'TB' # Top, Bottom, Left, Right (any combination)    

    # Style header
    for j in range(len(df_bill.columns)):
        table[0, j].set_text_props(weight='bold')

    # Style rows: left for description, right for amount
    for i in range(0, len(df_bill)+1):
        table[i, 0].set_text_props(ha='left')
        table[i, 1].set_text_props(ha='right')
        # Optionally bold total row (last row)
        if i == len(df_bill):
            table[i, 1].set_text_props(weight='bold')
            table[i, 0].set_text_props(weight='bold')
    fig.subplots_adjust(top=1, bottom=0, left=0, right=1, hspace=0, wspace=0)
    
    #fig.tight_layout()
    return fig

def plot_bill_style2(df):
    df_bill = df[['Opis','Stanje od','Stanje do','Potrošak']].copy()
    df_bill['Potrošak'] = df_bill['Potrošak'].apply(lambda x: f"{x:,.0f}" if pd.notnull(x) else "")  
    df_bill['Stanje od'] = df_bill['Stanje od'].apply(lambda x: f"{x:,.2f}" if pd.notnull(x) else "") 
    df_bill['Stanje do'] = df_bill['Stanje do'].apply(lambda x: f"{x:,.2f}" if pd.notnull(x) else "")   
    
    df_bill.loc[11, 'Stanje od'] = ''
    df_bill.loc[11, 'Stanje do'] = '' 
    df_bill.loc[11, 'Potrošak'] = ''


    #fig, ax = plt.subplots(figsize=(12, 0.7 + 0.55*len(df_bill)))
    fig, ax = plt.subplots(figsize=(12, 0.08 * len(df_bill)))
    
    ax.axis('off')

    table = ax.table(
        cellText=df_bill.values,
        colLabels=df_bill.columns,
        cellLoc='left',
        loc='top',
        colWidths=[0.3, 0.15,0.15,0.15],
        edges='open'
    )
    table.auto_set_font_size(False)
    table.set_fontsize(12)
    table.scale(1, 1)
    for  i in range (4):
        cell = table[0, i]  # row i, column j
        cell.visible_edges = 'B' # Top, Bottom, Left, Right (any combination)
        cell = table[len(df_bill), i]  # row i, column j
        cell.visible_edges = 'B' # Top, Bottom, Left, Right (any combination)    

    # Style header
    for j in range(len(df_bill.columns)):
        table[0, j].set_text_props(weight='bold')

    # Style rows: left for description, right for amount
    for i in range(0, len(df_bill)+1):
        table[i, 0].set_text_props(ha='left')
        table[i, 1].set_text_props(ha='center')
        table[i, 2].set_text_props(ha='center')
        table[i, 3].set_text_props(ha='center')
        
    fig.subplots_adjust(top=1, bottom=0, left=0, right=1, hspace=0, wspace=0)
    
    #fig.tight_layout()
    return fig

def plot_bill_style3(df):
    df_bill = df[['Opis','Iznos EUR','Količina','Jedinica mjere','Cijena EUR/kWh']].copy() 
    df_bill['Iznos EUR'] = df_bill['Iznos EUR'].apply(lambda x: f"{x:,.2f}" if pd.notnull(x) else "") 
    df_bill['Količina'] = df_bill['Količina'].apply(lambda x: f"{x:,.0f}" if pd.notnull(x) else "") 
    df_bill['Jedinica mjere'] = df_bill['Jedinica mjere'].apply(lambda x: "" if pd.isnull(x) else x)
    df_bill['Cijena EUR/kWh'] = df_bill['Cijena EUR/kWh'].apply(lambda x: f"{x:,.6f}" if pd.notnull(x) else "")
    df_bill['Cijena EUR/kWh'] = df_bill['Cijena EUR/kWh'].apply(lambda x: "" if pd.isnull(x) else x)

    df_bill.rename(columns={'Cijena EUR/kWh': 'EUR/kWh'}, inplace=True)
    df_bill.rename(columns={'Jedinica mjere': 'Jedinica'}, inplace=True)   

    fig, ax = plt.subplots(figsize=(12, 0.01 * len(df_bill)))    
    ax.axis('off')

    table = ax.table(
        cellText=df_bill.values,
        colLabels=df_bill.columns,
        cellLoc='left',
        loc='top',
        colWidths=[0.5, 0.1,0.1,0.05,0.1],
        edges='open'
    )
    table.auto_set_font_size(False)
    table.set_fontsize(12)
    table.scale(1, 1)
    for  i in range (5):
        cell = table[0, i]  # row i, column j
        cell.visible_edges = 'B' # Top, Bottom, Left, Right (any combination)
        cell = table[len(df_bill), i]  # row i, column j
        cell.visible_edges = 'B' # Top, Bottom, Left, Right (any combination)    

    # Style header
    for j in range(len(df_bill.columns)):
        table[0, j].set_text_props(weight='bold')

    # Style rows: left for description, right for amount
    for i in range(0, len(df_bill)+1):
        table[i, 0].set_text_props(ha='left')
        table[i, 1].set_text_props(ha='center')
        table[i, 2].set_text_props(ha='center')
        table[i, 3].set_text_props(ha='center')
        table[i, 4].set_text_props(ha='center')
    for i in range(0, len(df_bill)+1):
        if i in ([4,7, 13,14]):
            for j in range(5):
                table[i, j].set_text_props(weight='bold')
                cell = table[i, j]
                cell.visible_edges = 'T' # Top, Bottom, Left, Right (any combination
            for j in [2,3,4]:
                table[i, j].get_text().set_text("")
        elif i in ([17,18]):
            for j in range(2):
                table[i, j].set_text_props(weight='bold')          
        fig.subplots_adjust(top=1, bottom=0, left=0, right=1, hspace=0, wspace=0)      
    return fig