import React, {useEffect, useState} from 'react';
import {CheckIcon, MixerHorizontalIcon} from '@radix-ui/react-icons';
import {Button} from './ui/button';

const lines = text => text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);

export function RulesEditor({api, connected}) {
  const [saved, setSaved] = useState(null);
  const [remove, setRemove] = useState('');
  const [conditional, setConditional] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  function populate(value) {
    setSaved(value); setRemove(value.remove.join('\n')); setConditional(value.afterResolution.join('\n'));
  }
  useEffect(() => {
    if (!connected) return;
    let live = true;
    setBusy(true);
    api('rules').then(value => {if (live) populate(value);})
      .catch(e => {if (live) setError(e.message);})
      .finally(() => {if (live) setBusy(false);});
    return () => {live = false;};
  }, [connected]);
  const value = {version: 1, remove: lines(remove), afterResolution: lines(conditional)};
  const changed = saved && JSON.stringify(value) !== JSON.stringify(saved);
  async function save(e) {
    e.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {populate(await api('rules', {method:'PUT', body:JSON.stringify(value)})); setMessage('Rules saved. They apply to newly submitted imports.');}
    catch(e) {setError(e.message);}
    finally {setBusy(false);}
  }
  return <section className="card rules-card" id="rules">
    <div className="section-heading"><h2><MixerHorizontalIcon/>Naming rules</h2><span className="badge muted">{changed ? 'UNSAVED' : 'ACTIVE'}</span></div>
    <p>Filtered strings, one per line. Matching ignores case and treats punctuation literally.</p>
    {!connected ? <p className="rules-connect">Connect to your workspace to view and edit the rules.</p> : <form onSubmit={save}>
      <div className="rule-group"><label htmlFor="remove-rules">Always remove</label><textarea id="remove-rules" className="rules-input" rows={8} value={remove} disabled={!saved || busy} onChange={e=>{setRemove(e.target.value);setMessage('');}}/><p>Removes matching whole tags anywhere in the filename.</p></div>
      <div className="rule-group"><label htmlFor="conditional-rules">Remove only after a resolution</label><textarea id="conditional-rules" className="rules-input" rows={3} value={conditional} disabled={!saved || busy} onChange={e=>{setConditional(e.target.value);setMessage('');}}/><p>Requires a resolution directly before the tag, such as <code>1080p</code> or <code>2160p</code><br/>The resolution tag is maintained.</p></div>
      {error && <p role="alert" className="error rules-feedback">{error}</p>}
      {message && <p role="status" className="rules-feedback rules-success"><CheckIcon/>{message}</p>}
      <div className="rules-actions"><Button type="button" variant="outline" disabled={!changed || busy} onClick={()=>{populate(saved);setError('');setMessage('');}}>Discard changes</Button><Button type="submit" disabled={!changed || busy}>{busy ? 'Loading…' : 'Save rules'}</Button></div>
      <p className="rules-note">Saved rules persist across restarts. Existing and queued imports keep the rules they started with.</p>
    </form>}
  </section>;
}
