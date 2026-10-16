import { defineConfig } from 'vite';
const backend = process.env.AGENTGUARD_PROXY || 'http://127.0.0.1:8911';
export default defineConfig({server:{proxy:{'/api':backend,'/ws':{target:backend.replace('http','ws'),ws:true}}}});
