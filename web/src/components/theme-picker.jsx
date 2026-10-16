import React, {useState} from 'react';
import {SunIcon} from '@radix-ui/react-icons';
import themes from '../themes.json';

const STORAGE_KEY = 'mega-renamer-theme';
function applyTheme(id) {
  const preset = themes.find(theme => theme.id === id) || themes[0];
  const root = document.documentElement;
  root.dataset.theme = preset.id;
  root.style.colorScheme = preset.scheme;
  for (const [name, color] of Object.entries(preset.colors)) root.style.setProperty('--' + name, color);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', preset.colors.bg);
  return preset.id;
}
let initial = themes[0].id;
try {initial = localStorage.getItem(STORAGE_KEY) || initial;} catch { /* Browser storage may be disabled. */ }
initial = applyTheme(initial);

export function ThemePicker() {
  const [theme, setTheme] = useState(initial);
  function change(event) {
    const id = applyTheme(event.target.value);
    setTheme(id);
    try {localStorage.setItem(STORAGE_KEY, id);} catch { /* Theme still works for this visit. */ }
  }
  return <div className="theme-picker"><SunIcon aria-hidden="true"/><label htmlFor="theme">Theme</label><select id="theme" value={theme} onChange={change}>
    {['light', 'dark'].map(scheme => <optgroup key={scheme} label={scheme === 'light' ? 'Light' : 'Dark'}>
      {themes.filter(preset => preset.scheme === scheme).map(preset => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
    </optgroup>)}
  </select></div>;
}
