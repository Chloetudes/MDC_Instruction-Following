let passed = 0;
let failed = 0;

function assert(condition, name, detail) {
  if (condition) {
    console.log('  PASS  ' + name);
    passed++;
  } else {
    console.log('  FAIL  ' + name + (detail ? ' -- ' + detail : ''));
    failed++;
  }
}

function assertClose(a, b, tol, name) {
  assert(Math.abs(a - b) <= tol, name, 'got ' + a + ', expected ~' + b);
}

function icc_2_1(s1, s2) {
  if (!s1 || !s2) return NaN;
  var n = s1.length;
  if (n < 2 || s2.length !== n) return NaN;
  var k = 2;
  var sum = 0;
  for (var i = 0; i < n; i++) sum += s1[i] + s2[i];
  var grandMean = sum / (n * k);

  var subjectMeans = [];
  for (var i = 0; i < n; i++) subjectMeans.push((s1[i] + s2[i]) / 2);

  var raterMean0 = 0, raterMean1 = 0;
  for (var i = 0; i < n; i++) { raterMean0 += s1[i]; raterMean1 += s2[i]; }
  raterMean0 /= n; raterMean1 /= n;
  var raterMeans = [raterMean0, raterMean1];

  var ssBetweenSubjects = 0;
  for (var i = 0; i < n; i++) ssBetweenSubjects += Math.pow(subjectMeans[i] - grandMean, 2);
  ssBetweenSubjects *= k;

  var ssBetweenRaters = 0;
  for (var i = 0; i < 2; i++) ssBetweenRaters += Math.pow(raterMeans[i] - grandMean, 2);
  ssBetweenRaters *= n;

  var ssTotal = 0;
  for (var i = 0; i < n; i++) {
    ssTotal += Math.pow(s1[i] - grandMean, 2) + Math.pow(s2[i] - grandMean, 2);
  }
  var ssError = ssTotal - ssBetweenSubjects - ssBetweenRaters;

  var dfBetween = n - 1;
  var dfError = (n - 1) * (k - 1);
  var dfRater = k - 1;

  if (dfBetween === 0 || dfError === 0) return NaN;

  var msBetween = ssBetweenSubjects / dfBetween;
  var msRater = ssBetweenRaters / dfRater;
  var msError = ssError / dfError;

  var denom = msBetween + (k - 1) * msError + k * (msRater - msError) / n;
  if (denom <= 0) return NaN;

  var icc = (msBetween - msError) / denom;
  return Math.max(-1, Math.min(1, icc));
}

function icc_2_1_old(s1, s2) {
  var n = s1.length;
  var sum = 0;
  for (var i = 0; i < n; i++) sum += s1[i] + s2[i];
  var grandMean = sum / (n * 2);
  var subjectMeans = [];
  for (var i = 0; i < n; i++) subjectMeans.push((s1[i] + s2[i]) / 2);
  var ssBetween = 0;
  for (var i = 0; i < n; i++) ssBetween += Math.pow(subjectMeans[i] - grandMean, 2);
  var msBetween = ssBetween * 2 / (n - 1);
  var ssResidual = 0;
  for (var i = 0; i < n; i++) ssResidual += Math.pow(s1[i] - s2[i], 2) / 2;
  var msResidual = ssResidual / (n - 1);
  if (msBetween + msResidual > 0) return (msBetween - msResidual) / (msBetween + msResidual);
  return 0;
}

function normalizedMAE(s1, s2, scoreRange) {
  if (!s1 || !s2) return NaN;
  var mae = 0;
  for (var i = 0; i < s1.length; i++) mae += Math.abs(s1[i] - s2[i]);
  mae /= s1.length;
  if (scoreRange === undefined || scoreRange === null) {
    var combined = s1.concat(s2);
    var mn = combined[0], mx = combined[0];
    for (var i = 1; i < combined.length; i++) {
      if (combined[i] < mn) mn = combined[i];
      if (combined[i] > mx) mx = combined[i];
    }
    scoreRange = mx - mn;
  }
  if (scoreRange <= 0) return 0;
  return mae / scoreRange;
}

function detectAnnotators(columns) {
  var annotators = {};
  for (var i = 0; i < columns.length; i++) {
    var col = columns[i];
    if (col.indexOf('ann') === 0 && col.indexOf('score') !== -1) {
      var prefix = col.split('_')[0];
      annotators[prefix] = true;
    }
  }
  return Object.keys(annotators).sort();
}

function compositeScore(spearman, icc, kappa, nmae) {
  return spearman * 0.4 + icc * 0.3 + kappa * 0.2 + (1 - nmae) * 0.1;
}

function compositeScoreOld(spearman, icc, kappa, mae) {
  return spearman * 0.4 + icc * 0.3 + kappa * 0.2 + (1 - mae / 100) * 0.1;
}

console.log('\n==============================================');
console.log('  统计分析模块修复验证测试');
console.log('==============================================\n');

console.log('[1] ICC(2,1) 公式修复验证');

var perfectS = [1, 2, 3, 4, 5, 6, 7, 8];
assertClose(icc_2_1(perfectS, perfectS), 1.0, 0.01, 'perfect agreement => ICC ~= 1.0');

var s1 = [1, 3, 5, 7, 9];
var s2 = [1.5, 3.5, 5.5, 7.5, 9.5];
var iccNew = icc_2_1(s1, s2);
assert(iccNew > 0.9, 'high correlation => ICC > 0.9', 'got ' + iccNew.toFixed(4));
assert(iccNew >= -1 && iccNew <= 1, 'ICC in [-1, 1]');

var oppositeS1 = [1, 2, 3, 4, 5];
var oppositeS2 = [5, 4, 3, 2, 1];
var iccNewOpposite = icc_2_1(oppositeS1, oppositeS2);
var iccOldOpposite = icc_2_1_old(oppositeS1, oppositeS2);
assert(iccNewOpposite <= 0, 'opposite scores => ICC <= 0 (new formula correct)');
console.log('    新公式 ICC = ' + iccNewOpposite.toFixed(4) + ', 旧公式 ICC = ' + iccOldOpposite.toFixed(4));

var biasS1 = [3, 5, 7, 4, 6, 8, 2, 9];
var biasS2 = biasS1.map(function(v) { return v + 2; });
var iccNewBias = icc_2_1(biasS1, biasS2);
var iccOldBias = icc_2_1_old(biasS1, biasS2);
assert(iccNewBias < iccOldBias, '系统偏差: 新公式ICC < 旧公式ICC (新公式正确惩罚系统偏差)');
console.log('    系统偏差场景: 新公式 ICC = ' + iccNewBias.toFixed(4) + ', 旧公式 ICC = ' + iccOldBias.toFixed(4));

assert(isNaN(icc_2_1([1], [1])), 'n=1 => NaN');
assert(isNaN(icc_2_1(null, [1, 2])), 'null input => NaN');

console.log('\n[2] 归一化 MAE 验证');

assertClose(normalizedMAE([1, 2, 3], [1, 2, 3]), 0.0, 0.001, 'perfect agreement => nMAE = 0');
assertClose(normalizedMAE([0, 0, 0], [10, 10, 10], 10), 1.0, 0.001, 'max disagreement => nMAE = 1');

var nmaeMixed = normalizedMAE([1, 5, 9], [2, 5, 8]);
assert(nmaeMixed > 0 && nmaeMixed <= 1, 'mixed scores => nMAE in (0,1]: ' + nmaeMixed.toFixed(4));

var nmaeLarge = normalizedMAE([0, 50, 100], [10, 50, 90], 100);
var nmaeSmall = normalizedMAE([0, 5, 10], [1, 5, 9], 10);
assertClose(nmaeLarge, nmaeSmall, 0.001, '100分制与10分制归一化MAE一致（量纲无关）');

assert(isNaN(normalizedMAE(null, [1, 2])), 'null input => NaN');

console.log('\n[3] 标注员自动检测验证');

var r1 = detectAnnotators(['ann1_score', 'ann2_score', 'qid']);
assert(JSON.stringify(r1) === '["ann1","ann2"]', '标准两标注员检测');

var r2 = detectAnnotators(['ann1_score', 'ann2_score', 'ann3_score']);
assert(JSON.stringify(r2) === '["ann1","ann2","ann3"]', '三标注员检测');

var r3 = detectAnnotators(['ann1_score_m1', 'ann1_score_m2', 'ann2_score_m1']);
assert(JSON.stringify(r3) === '["ann1","ann2"]', '多模型评分列去重');

var r4 = detectAnnotators(['query', 'model', 'eval_score']);
assert(JSON.stringify(r4) === '[]', '无标注员列返回空数组');

var r5 = detectAnnotators(['ann1_score', 'ann2_score', 'ann1_name', 'ann2_name', 'qid']);
assert(JSON.stringify(r5) === '["ann1","ann2"]', '混合列名正确过滤');

console.log('\n[4] 综合质量得分公式验证（归一化MAE替代硬编码100分制）');

var mae10Scale = 1.0;
var nmae10Scale = mae10Scale / 10;
var oldScore10 = compositeScoreOld(0.8, 0.7, 0.6, mae10Scale);
var newScore10 = compositeScore(0.8, 0.7, 0.6, nmae10Scale);

var mae100Scale = 1.0;
var nmae100Scale = mae100Scale / 100;
var oldScore100 = compositeScoreOld(0.8, 0.7, 0.6, mae100Scale);
var newScore100 = compositeScore(0.8, 0.7, 0.6, nmae100Scale);

assertClose(oldScore10, oldScore100, 0.001, '旧公式：10分制和100分制MAE=1得分相同（量纲不敏感，这是BUG）');
assert(Math.abs(newScore10 - newScore100) > 0.005, '新公式：10分制和100分制归一化后得分不同（量纲敏感，正确）');
console.log('    旧公式: 10分制=' + oldScore10.toFixed(4) + ', 100分制=' + oldScore100.toFixed(4));
console.log('    新公式: 10分制=' + newScore10.toFixed(4) + ', 100分制=' + newScore100.toFixed(4));

console.log('\n==============================================');
console.log('  测试结果: ' + passed + ' 通过 / ' + failed + ' 失败 / ' + (passed + failed) + ' 总计');
console.log('==============================================\n');

if (failed > 0) {
  process.exit(1);
}
