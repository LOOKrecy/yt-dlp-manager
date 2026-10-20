/* Pure selection/size rules shared by the UI and behavioral tests. No network. */
const FormatLogic = (() => {
  const empty = () => ({video:'', audio:'', muxed:'', expert:''});
  function restore(expression, formats) {
    const result = empty(), text = expression.trim();
    if (!text) return result;
    if (!/^[A-Za-z0-9_.-]+(?:\+[A-Za-z0-9_.-]+)?$/.test(text)) return {...result,expert:text};
    const ids = text.split('+');
    for (const id of ids) {
      const item = formats.find(f => f.format_id === id);
      if (!item || !['audio','video','muxed'].includes(item.kind) || result[item.kind]) return {...empty(),expert:text};
      result[item.kind] = id;
    }
    if (result.muxed && ids.length !== 1) return {...empty(),expert:text};
    return result;
  }
  function expression(selection) {
    return selection.expert || selection.muxed || [selection.video,selection.audio].filter(Boolean).join('+');
  }
  function choose(selection, item, role, replaceMuxed=false) {
    const kind = item.kind === 'unknown' ? role : item.kind;
    if (!['audio','video','muxed'].includes(kind)) return selection;
    if (kind === 'audio' && selection.muxed && !replaceMuxed) return selection;
    if (kind === 'muxed') return {...empty(),muxed:item.format_id};
    const next = {...selection,expert:'',muxed:''};
    next[kind] = item.format_id;
    return next;
  }
  const valid = value => typeof value === 'number' && Number.isFinite(value) && value > 0;
  function estimate(formats, text, options={}) {
    if (options.mode && options.mode !== 'manual') return {pending:true,conversion:options.mode==='audio'};
    const selected = restore(text, formats);
    if (!text || selected.expert) return {pending:true};
    const ids = [selected.muxed,selected.video,selected.audio].filter(Boolean);
    let known = 0, unknown = 0, approximate = false;
    for (const id of ids) {
      const item = formats.find(f => f.format_id === id);
      let size = item.size_bytes, source = item.size_source;
      if (options.section) {
        const duration = valid(item.duration) ? Math.min(options.section,Math.max(0,item.duration-(options.sectionStart||0))) : options.section;
        if (!valid(duration)) size = null;
        else if (valid(item.bitrate)) size = duration * item.bitrate * 1000 / 8;
        else if (valid(item.duration) && valid(size)) size *= Math.min(1,duration/item.duration);
        else size = null;
        source = 'bitrate_estimate';
      }
      if (valid(size)) {known += size; approximate ||= source !== 'exact';} else unknown++;
    }
    return {known:known||null,unknown,approximate,conversion:!!options.conversion};
  }
  function describe(result, bytes) {
    if (result.pending) return 'Оценка появится после определения потоков' + (result.conversion ? '; размер после аудиоконвертации неизвестен' : ' (экспертное выражение ещё не разрешено)');
    let text = result.known == null ? 'Размер неизвестен' : result.unknown ? `Известная часть: ${bytes(result.known)}; размер другой дорожки неизвестен` : `${result.approximate?'Примерно ':''}${bytes(result.known)}`;
    if (result.conversion) text = `Исходный размер: ${text}; размер после конвертации неизвестен и зависит от кодека/битрейта`;
    return text;
  }
  return {empty,restore,expression,choose,estimate,describe};
})();
if (typeof module !== 'undefined') module.exports = FormatLogic;
