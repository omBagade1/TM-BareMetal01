import { useEffect, useRef, type ReactNode } from 'react';
import { ZipperScrollbar } from './ZipperScrollbar';

/** Preserve the original element (including textarea editing and resize) as the viewport. */
export function ScrollFrame({ children, label, inline = false }: { children: ReactNode; label: string; inline?: boolean }) {
  const frame = useRef<HTMLDivElement & HTMLSpanElement>(null);
  useEffect(() => { frame.current?.firstElementChild?.dispatchEvent(new Event('zipper-measure')); });
  const Tag = inline ? 'span' : 'div';
  return <Tag ref={frame} className="zipper-frame zipper-field">
    {children}
    <ZipperScrollbar targetRef={frame} selector=":scope > :first-child" label={`${label} vertical scrollbar`}/>
    <ZipperScrollbar targetRef={frame} selector=":scope > :first-child" label={`${label} horizontal scrollbar`} horizontal/>
  </Tag>;
}
