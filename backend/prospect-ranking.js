// Step 5 ranks already-scored prospects. It never invents or changes the Step 4 score.
const confidenceWeight={high:3,medium:2,low:1};

function num(v){const n=Number(v);return Number.isFinite(n)?n:0}

export function rankProspects(prospects=[]){
  return prospects
    .map((p,index)=>{
      const score=p?.score||{};
      const confidence=String(score.confidence||'low').toLowerCase();
      const gaps=Array.isArray(score.gaps)?score.gaps:[];
      const actionableGapWeight=gaps.reduce((n,g)=>n+Math.max(0,num(g?.weight)),0);
      return {
        prospect:p,
        _index:index,
        _score:num(score.score),
        _confidence:confidenceWeight[confidence]||1,
        _gapWeight:actionableGapWeight,
        _gapCount:gaps.length
      };
    })
    .sort((a,b)=>
      b._score-a._score ||
      b._confidence-a._confidence ||
      b._gapWeight-a._gapWeight ||
      b._gapCount-a._gapCount ||
      a._index-b._index
    )
    .map((entry,index)=>({
      ...entry.prospect,
      rank:index+1,
      ranking:{
        rank:index+1,
        score:num(entry.prospect?.score?.score),
        opportunity:entry.prospect?.score?.opportunity||'Low',
        priority:entry.prospect?.score?.priority||'P4',
        confidence:entry.prospect?.score?.confidence||'low',
        actionableGapWeight:entry._gapWeight,
        actionableGapCount:entry._gapCount,
        rankingReason:index===0?'Highest Step 4 opportunity score among the supplied prospects.':'Ordered by Step 4 score, then evidence confidence, then actionable gap weight.'
      }
    }));
}

export function summarizeRanking(ranked=[]){
  return {
    ranked:ranked.length,
    topOpportunity:ranked[0]?.score?.opportunity||null,
    topScore:ranked.length?num(ranked[0]?.score?.score):null,
    p1:ranked.filter(p=>p?.score?.priority==='P1').length,
    p2:ranked.filter(p=>p?.score?.priority==='P2').length,
    p3:ranked.filter(p=>p?.score?.priority==='P3').length,
    p4:ranked.filter(p=>p?.score?.priority==='P4').length
  };
}
