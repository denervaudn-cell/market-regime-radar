
const TD="https://api.twelvedata.com/time_series";
const FRED_CSV="https://fred.stlouisfed.org/graph/fredgraph.csv?id=";

const sectors=["XLB","XLC","XLE","XLF","XLI","XLK","XLP","XLRE","XLU","XLV","XLY"];
const benchmark="SPY";
const FULL_UNIVERSE_START="2018-06-19";

const exposure={
 XLB:{rates:-.1,inflation:.8,vol:-.2,credit:-.1,value:.4},
 XLC:{rates:-.4,inflation:0,vol:-.2,credit:0,value:-.3},
 XLE:{rates:.1,inflation:1,vol:-.1,credit:0,value:.8},
 XLF:{rates:.8,inflation:.2,vol:-.1,credit:-.5,value:.8},
 XLI:{rates:.1,inflation:.5,vol:-.2,credit:-.2,value:.4},
 XLK:{rates:-1,inflation:-.2,vol:-.4,credit:0,value:-1},
 XLP:{rates:-.3,inflation:.1,vol:.7,credit:.2,value:.2},
 XLRE:{rates:-1,inflation:.2,vol:-.3,credit:-.8,value:.1},
 XLU:{rates:-1,inflation:0,vol:.5,credit:-.2,value:.2},
 XLV:{rates:-.2,inflation:0,vol:.7,credit:.2,value:.2},
 XLY:{rates:-.6,inflation:-.2,vol:-.5,credit:-.4,value:-.4}
};

function mean(a){return a.reduce((s,x)=>s+x,0)/a.length}
function std(a){if(a.length<2)return 0;const m=mean(a);return Math.sqrt(a.reduce((s,x)=>s+(x-m)**2,0)/(a.length-1))}
function z(arr,x){const s=std(arr);return s?(x-mean(arr))/s:0}
function clamp(x,a,b){return Math.max(a,Math.min(b,x))}
function ret(a,b){return a&&b?b/a-1:null}

async function tdSeries(symbol,key,start){
  const u=new URL(TD);
  u.searchParams.set("symbol",symbol);
  u.searchParams.set("interval","1day");
  u.searchParams.set("start_date",start);
  u.searchParams.set("outputsize","5000");
  u.searchParams.set("adjust","all");
  u.searchParams.set("apikey",key);
  const r=await fetch(u);
  const j=await r.json();
  if(!r.ok||!j.values)throw new Error(`Twelve Data ${symbol}: ${j.message||r.status}`);
  return j.values.slice().reverse().map(x=>({date:x.datetime,v:Number(x.close)})).filter(x=>Number.isFinite(x.v));
}

async function fred(id,start){
  const u=FRED_CSV+encodeURIComponent(id);
  const r=await fetch(u);
  if(!r.ok)throw new Error(`FRED ${id}: ${r.status}`);
  const t=await r.text();
  const lines=t.trim().split(/\r?\n/);
  const out=[];
  for(let i=1;i<lines.length;i++){
    const parts=lines[i].split(",");
    const date=parts[0], v=Number(parts[1]);
    if(date>=start && Number.isFinite(v)) out.push({date,v});
  }
  return out;
}

function monthEnd(series){
  const m=new Map();
  for(const x of series)m.set(x.date.slice(0,7),x);
  return [...m.entries()].map(([month,x])=>({month,date:x.date,v:x.v}));
}
function monthlyMap(series){return new Map(monthEnd(series).map(x=>[x.month,x.v]))}
function previousMonths(keys,idx,n){return keys.slice(Math.max(0,idx-n),idx)}

function stats(rets,hitAgainst=null,turnover=0){
  if(!rets.length)return {};
  const growth=rets.reduce((a,r)=>a*(1+r),1);
  const years=rets.length/12;
  const cagr=Math.pow(growth,1/years)-1;
  const annVol=std(rets)*Math.sqrt(12);
  const sharpe=annVol?cagr/annVol:null;
  let eq=1,peak=1,mdd=0;
  for(const r of rets){eq*=1+r;peak=Math.max(peak,eq);mdd=Math.min(mdd,eq/peak-1)}
  return {cagr,annVol,sharpe,maxDrawdown:mdd,hitRate:hitAgainst?rets.filter((r,i)=>r>hitAgainst[i]).length/rets.length:null,turnover,avgHoldings:1};
}

function yearly(rows){
  const by={};
  rows.forEach(x=>{const y=x.date.slice(0,4);(by[y]??=[]).push(x)});
  return Object.entries(by).map(([year,a])=>{
    const s=a.reduce((g,x)=>g*(1+x.sret),1)-1;
    const b=a.reduce((g,x)=>g*(1+x.bret),1)-1;
    return {year,strategy:s,benchmark:b,excess:s-b};
  });
}

export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  const tdKey=process.env.TWELVE_DATA_API_KEY;
  if(!tdKey){
    return res.status(503).json({ok:false,error:"Real backtest requires TWELVE_DATA_API_KEY. FRED series are loaded from public CSV and do not require a key."});
  }

  const requestedStart=req.query.start||FULL_UNIVERSE_START;
  const start=requestedStart<FULL_UNIVERSE_START?FULL_UNIVERSE_START:requestedStart;
  const rebalance=req.query.rebalance||"monthly";
  const topN=Math.max(1,Math.min(5,Number(req.query.topN)||3));
  const costBps=Math.max(0,Number(req.query.costBps)||10);
  const shortBorrowBps=Math.max(0,Number(req.query.shortBorrowBps)||50);
  const mode=req.query.mode||"extreme1";

  if(rebalance!=="monthly"){
    return res.status(400).json({ok:false,error:"Real engine currently supports monthly rebalancing only."});
  }

  try{
    const [pricePairs,dgs2,dgs10,real10,bei10,vix,hy,dff]=await Promise.all([
      Promise.all([...sectors,benchmark].map(async s=>[s,await tdSeries(s,tdKey,start)])),
      fred("DGS2",start),
      fred("DGS10",start),
      fred("DFII10",start),
      fred("T10YIE",start),
      fred("VIXCLS",start),
      fred("BAMLH0A0HYM2",start),
      fred("DFF",start)
    ]);

    const prices=Object.fromEntries(pricePairs.map(([s,a])=>[s,monthlyMap(a)]));
    const macro={
      dgs2:monthlyMap(dgs2), dgs10:monthlyMap(dgs10), real10:monthlyMap(real10),
      bei10:monthlyMap(bei10), vix:monthlyMap(vix), hy:monthlyMap(hy), dff:monthlyMap(dff)
    };

    const keys=[...prices[benchmark].keys()].filter(k=>k>=start.slice(0,7)).sort();
    const rows=[]; let prevLong=[],turnoverSum=0;

    for(let i=13;i<keys.length-1;i++){
      const m=keys[i], next=keys[i+1];
      if(![macro.dgs2,macro.dgs10,macro.real10,macro.bei10,macro.vix,macro.hy,macro.dff].every(mp=>mp.has(m)))continue;
      if(![...sectors,benchmark].every(s=>prices[s].has(m)&&prices[s].has(next)))continue;

      const hist=previousMonths(keys,i,60);
      const slope=macro.dgs10.get(m)-macro.dgs2.get(m);
      const slopes=hist.filter(x=>macro.dgs10.has(x)&&macro.dgs2.has(x)).map(x=>macro.dgs10.get(x)-macro.dgs2.get(x));
      const reals=hist.filter(x=>macro.real10.has(x)).map(x=>macro.real10.get(x));
      const beis=hist.filter(x=>macro.bei10.has(x)).map(x=>macro.bei10.get(x));
      const vxs=hist.filter(x=>macro.vix.has(x)).map(x=>macro.vix.get(x));
      const credits=hist.filter(x=>macro.hy.has(x)).map(x=>macro.hy.get(x));
      if([slopes,reals,beis,vxs,credits].some(a=>a.length<12))continue;

      const state={
        rates:clamp(z(reals,macro.real10.get(m))/2,-1,1),
        curve:clamp(z(slopes,slope)/2,-1,1),
        inflation:clamp(z(beis,macro.bei10.get(m))/2,-1,1),
        vol:clamp(z(vxs,macro.vix.get(m))/2,-1,1),
        credit:clamp(z(credits,macro.hy.get(m))/2,-1,1)
      };

      const scored=[];
      for(const s of sectors){
        const mp=prices[s];
        const past6=keys[i-6];
        if(!past6||!mp.has(past6))continue;
        const momentum=ret(mp.get(past6),mp.get(m));
        const e=exposure[s];
        const macroScore =
          (-state.rates)*e.rates*18 +
          state.curve*e.rates*12 +
          state.inflation*e.inflation*14 +
          (-state.vol)*e.vol*10 +
          (-state.credit)*e.credit*12 +
          e.value*(state.rates*.25+state.inflation*.25)*8;
        const momScore=clamp(momentum/.20,-1,1)*22;
        scored.push({s,score:50+macroScore+momScore});
      }
      if(scored.length!==sectors.length)continue;
      scored.sort((a,b)=>b.score-a.score);

      const longs=mode==="extreme1"?[scored[0].s]:scored.slice(0,topN).map(x=>x.s);
      const shorts=mode==="extreme1"?[scored.at(-1).s]:scored.slice(-topN).map(x=>x.s);

      const rankWeights=mode==="extreme1"?[1]:(topN===3?[.50,.25,.25]:Array(topN).fill(1/topN));
      const weighted=(names)=>names.reduce((sum,s,idx)=>sum+ret(prices[s].get(m),prices[s].get(next))*rankWeights[idx],0);

      const unlevLong=weighted(longs), unlevShort=weighted(shorts);
      const bret=ret(prices[benchmark].get(m),prices[benchmark].get(next));
      const turnover=prevLong.length?1-longs.filter(x=>prevLong.includes(x)).length/longs.length:1;
      prevLong=longs;turnoverSum+=turnover;

      const tradingCost=turnover*(costBps/10000)*2;
      const annualFunding=macro.dff.get(m)/100;
      const monthlyFunding=annualFunding/12;
      const monthlyBorrow=(shortBorrowBps/10000)/12;

      let sret,lsret,longRet,shortRet;
      if(mode==="extreme1"){
        longRet=2*unlevLong;
        shortRet=2*unlevShort;
        // Conservative explicit cost model:
        // charge funding on one extra long notional (100%) plus borrow fee on full 200% short notional.
        const financingCost=monthlyFunding + 2*monthlyBorrow;
        lsret=longRet-shortRet-tradingCost-financingCost;
        sret=lsret;
      }else{
        longRet=unlevLong;
        shortRet=unlevShort;
        const financingCost=monthlyBorrow;
        lsret=longRet-shortRet-tradingCost-financingCost;
        sret=longRet-tradingCost/2;
      }

      rows.push({
        date:next,sret,bret,lsret,longRet,shortRet,longs,shorts,state,
        fundingRate:annualFunding,shortBorrowAnnual:shortBorrowBps/10000
      });
    }

    if(rows.length<12)throw new Error("Not enough overlapping real history across all 11 sector ETFs and macro series.");

    let se=100,be=100,le=100;
    const equityCurve=[],longShortCurve=[];
    for(const x of rows){
      se*=1+x.sret;be*=1+x.bret;le*=1+x.lsret;
      equityCurve.push({date:x.date,strategy:Number(se.toFixed(2)),benchmark:Number(be.toFixed(2))});
      longShortCurve.push({date:x.date,value:Number(le.toFixed(2))});
    }

    let persist=0,run=1,runs=[];
    for(let i=1;i<rows.length;i++){
      const same=rows[i].longs[0]===rows[i-1].longs[0]&&rows[i].shorts[0]===rows[i-1].shorts[0];
      if(same){persist++;run++}else{runs.push(run);run=1}
    }
    runs.push(run);

    const diagnostics={
      topBeatsBottom:rows.filter(x=>x.longRet/2>x.shortRet/2).length/rows.length,
      positiveSpreadAfterCosts:rows.filter(x=>x.lsret>0).length/rows.length,
      avgMonthlySpread:mean(rows.map(x=>x.longRet/2-x.shortRet/2)),
      avgLongReturn:mean(rows.map(x=>x.longRet/2)),
      avgShortReturn:mean(rows.map(x=>x.shortRet/2)),
      rankPersistence:rows.length>1?persist/(rows.length-1):null,
      avgHoldingMonths:runs.length?mean(runs):null
    };

    const srets=rows.map(x=>x.sret),brets=rows.map(x=>x.bret);
    return res.status(200).json({
      ok:true,
      meta:{
        start:rows[0].date,end:rows.at(-1).date,months:rows.length,rebalance,topN,costBps,shortBorrowBps,mode,
        source:"Twelve Data adjusted=all + FRED public CSV",
        universeStart:FULL_UNIVERSE_START,
        fundingSeries:"DFF"
      },
      stats:{
        strategy:stats(srets,brets,turnoverSum/(rows.length/12)),
        benchmark:stats(brets)
      },
      equityCurve,longShortCurve,annual:yearly(rows),
      latest:{longs:rows.at(-1).longs,shorts:rows.at(-1).shorts,state:rows.at(-1).state},
      holdings:rows.map(x=>({date:x.date,longs:x.longs,shorts:x.shorts,excess:x.sret-x.bret,fundingRate:x.fundingRate})),
      diagnostics
    });
  }catch(e){
    return res.status(500).json({ok:false,error:String(e.message||e)});
  }
}
