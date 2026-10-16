import { createHighlighterCore } from 'shiki/core';
import { createJavaScriptRegexEngine } from 'shiki/engine/javascript';
import light from 'shiki/themes/github-light.mjs';
import dark from 'shiki/themes/github-dark.mjs';
const languages = {
  javascript: () => import('shiki/langs/javascript.mjs'),
  typescript: () => import('shiki/langs/typescript.mjs'),
  tsx: () => import('shiki/langs/tsx.mjs'), jsx: () => import('shiki/langs/jsx.mjs'),
  python: () => import('shiki/langs/python.mjs'), json: () => import('shiki/langs/json.mjs'),
  bash: () => import('shiki/langs/bash.mjs'), powershell: () => import('shiki/langs/powershell.mjs'),
  css: () => import('shiki/langs/css.mjs'), html: () => import('shiki/langs/html.mjs'),
  sql: () => import('shiki/langs/sql.mjs'), yaml: () => import('shiki/langs/yaml.mjs'),
};

const highlighter = createHighlighterCore({
  themes: [light, dark], langs: [],
  engine: createJavaScriptRegexEngine(),
});
const aliases: Record<string, string> = { js:'javascript', ts:'typescript', py:'python', sh:'bash', shell:'bash', ps1:'powershell', ps:'powershell', yml:'yaml' };
export async function highlight(code: string, language: string) {
  const h = await highlighter;
  const lang = aliases[language] || language;
  if (!Object.hasOwn(languages, lang)) return null;
  if (!h.getLoadedLanguages().includes(lang)) await h.loadLanguage((await languages[lang as keyof typeof languages]()).default);
  return h.codeToTokens(code, { lang, themes: {light:'github-light',dark:'github-dark'}, defaultColor: false }).tokens;
}
