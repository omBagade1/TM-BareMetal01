type Disposable = { dispose(): void };
declare class Terminal {
  constructor(options: Record<string, unknown>);
  cols: number;
  rows: number;
  options: { disableStdin: boolean; fontSize: number; theme: Record<string, string> };
  parser: { registerOscHandler(id: number, handler: (data: string) => boolean): Disposable };
  loadAddon(addon: FitAddon): void;
  open(element: HTMLElement): void;
  write(data: string, callback?: () => void): void;
  resize(cols: number, rows: number): void;
  reset(): void;
  focus(): void;
  getSelection(): string;
  paste(data: string): void;
  onSelectionChange(callback: () => void): Disposable;
  attachCustomKeyEventHandler(callback: (event: KeyboardEvent) => boolean): void;
  onData(callback: (data: string) => void): Disposable;
  onResize(callback: (size: { cols: number; rows: number }) => void): Disposable;
  dispose(): void;
}
declare class FitAddon { fit(): void; }
declare const xterm: { Terminal: typeof Terminal; FitAddon: typeof FitAddon };
export default xterm;
