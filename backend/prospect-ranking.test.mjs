import assert from 'node:assert/strict';
import { rankProspects, summarizeRanking } from './prospect-ranking.js';

const fixture = [
  {name:'Business C', score:{score:61,opportunity:'High',priority:'P2',confidence:'medium',gaps:[{label:'Booking',weight:16},{label:'Form',weight:14}]}},
  {name:'Business A', score:{score:82,opportunity:'Very high',priority:'P1',confidence:'high',gaps:[{label:'Booking',weight:16}]}},
  {name:'Business B', score:{score:82,opportunity:'Very high',priority:'P1',confidence:'medium',gaps:[{label:'Booking',weight:16},{label:'Form',weight:14}]}},
  {name:'Business D', score:{score:35,opportunity:'Moderate',priority:'P3',confidence:'high',gaps:[]}}
];

const ranked=rankProspects(fixture);
assert.deepEqual(ranked.map(p=>p.name),['Business A','Business B','Business C','Business D']);
assert.deepEqual(ranked.map(p=>p.rank),[1,2,3,4]);
assert.deepEqual(ranked.map(p=>p.score.score),[82,82,61,35]);
assert.equal(ranked[0].ranking.confidence,'high');
assert.equal(ranked[1].ranking.actionableGapWeight,30);
assert.equal(ranked[0].ranking.score,82);
assert.equal(summarizeRanking(ranked).topScore,82);
assert.equal(summarizeRanking(ranked).p1,2);

const stable=rankProspects([
  {name:'First',score:{score:50,confidence:'high',gaps:[]}},
  {name:'Second',score:{score:50,confidence:'high',gaps:[]}}
]);
assert.deepEqual(stable.map(p=>p.name),['First','Second']);

console.log('Step 5 ranking tests passed.');
