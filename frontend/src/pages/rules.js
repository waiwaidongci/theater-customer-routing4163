import {feedback, field} from '../components/common/fields.js';
import {panel} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, p} from '../utils/dom.js';
import {date} from '../utils/format.js';

export async function rulesPage(route, refresh) {
  const {spec} = workspace;
  const versions = await workspace.rules();
  const error = feedback();
  const list = table([
    {key:'version',label:'规则版本'},
    {label:'生效时刻（北京时间）',render:row=>date(row.effective_at)},
    {key:'issued_seq',label:'签发序号'},
    {label:'词表上限',render:row=>row.params.max_terms || '完整词表'},
    {label:'最低相似度',render:row=>row.params.min_similarity},
    {key:'author',label:'签发人'},
    {label:'登记时间',render:row=>date(row.created_at)},
  ], versions, {caption:'已发布规则版本', empty:'还没有已发布的分流规则，请先在右侧发布。'});
  const submit = button('发布规则版本', {type:'submit',class:'primary','data-testid':'publish-rule'});
  const form = session.canWrite && el('form',{class:'fields',onSubmit:handler(submit,error,async event=>{
    const data = new FormData(event.target);
    const moment = data.get('effective_at');
    if (!moment) throw new Error('请选择生效时刻');
    await workspace.publishRule({
      version:data.get('version'), effective_at:`${moment}:00+08:00`, issued_seq:Number(data.get('issued_seq')),
      params:Object.fromEntries(spec.params.map(param=>[param.key,data.get(param.key)])),
    });
    await refresh();
  })}, spec.rule_fields.map(item=>field(item)),
    el('div',{class:'form-grid'},spec.params.map(param=>field(param))), submit);
  return el('div',{class:'two-col'},el('div',{class:'wide-panel'},
    panel('已发布规则版本',p('演出调整后在此登记分流规则变更。同一生效时刻的变更按签发序号取唯一版本；版本重叠或来信缺规则时导入批次会被整批拒绝。','subtle'),list)),
    el('aside',{class:'sidebar-panel'},
      panel('发布新版本',p('发布是单事务操作：中断或校验失败时整体回滚，旧版本保持可查。','subtle'),
        form || p('只读角色可以查看已发布版本。','empty'),error),
      panel('验收口径',el('ul',{class:'method-list'},spec.methodology.slice(1,2).concat(spec.methodology.slice(5,6)).map(text=>el('li',{},text))))));
}
