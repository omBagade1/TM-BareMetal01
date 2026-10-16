import { useEffect, useId, useRef, useState, type RefObject } from 'react';
import './zipper-scrollbar.css';

/** An overlay for an existing native scroll viewport; never intercepts content input. */
export function ZipperScrollbar({ targetRef, selector, page = false, label, horizontal = false }: {
  targetRef?: RefObject<HTMLElement | null>; selector?: string; page?: boolean; label: string; horizontal?: boolean;
}) {
  const rail = useRef<HTMLDivElement>(null);
  const thumb = useRef<HTMLDivElement>(null);
  const target = useRef<HTMLElement | null>(null);
  const sync = useRef(() => {});
  const drag = useRef<{ id: number; offset: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const id = useId();

  useEffect(() => {
    const railEl = rail.current!;
    const thumbEl = thumb.current!;
    const frame = railEl.parentElement!;
    let current: HTMLElement | null = null;
    let addedId = false;
    let raf = 0;
    const measure = () => {
      if (!current) { railEl.hidden = true; return; }
      const height = page ? (horizontal ? window.innerWidth : window.innerHeight) : (horizontal ? current.clientWidth : current.clientHeight);
      const max = Math.max(0, (horizontal ? current.scrollWidth : current.scrollHeight) - height);
      railEl.hidden = max <= 1;
      const travel = Math.max(0, (horizontal ? railEl.clientWidth - thumbEl.offsetWidth : railEl.clientHeight - thumbEl.offsetHeight));
      const value = Math.max(0, Math.min(max, horizontal ? current.scrollLeft : current.scrollTop));
      thumbEl.style[horizontal ? 'left' : 'top'] = `${max ? value / max * travel : 0}px`;
      thumbEl.setAttribute('aria-valuemax', String(Math.round(max)));
      thumbEl.setAttribute('aria-valuenow', String(Math.round(value)));
      thumbEl.setAttribute('aria-valuetext', `${max ? Math.round(value / max * 100) : 0}% scrolled`);
      const edge = frame.getBoundingClientRect()[horizontal ? 'bottom' : 'right'];
      let inside = page || edge + 22 > (horizontal ? window.innerHeight : document.documentElement.clientWidth);
      for (let parent = frame.parentElement; parent && !inside; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (/(hidden|clip|auto|scroll)/.test((horizontal ? style.overflowY : style.overflowX)) && edge + 22 > parent.getBoundingClientRect()[horizontal ? 'bottom' : 'right']) inside = true;
      }
      railEl.dataset.inside = String(inside);
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; measure(); }); };
    const resize = new ResizeObserver(schedule);
    const contentChanges = new MutationObserver(() => { observeChildren(); schedule(); });
    const observeChildren = () => {
      resize.disconnect(); resize.observe(frame);
      if (current) { resize.observe(current); for (const child of current.children) resize.observe(child); }
    };
    const bind = () => {
      const next = page ? document.scrollingElement as HTMLElement :
        selector ? targetRef?.current?.querySelector<HTMLElement>(selector) : targetRef?.current;
      if (next === current) return;
      if (current) {
        current.classList.remove('zipper-native-scroll');
        current.removeEventListener('scroll', measure); current.removeEventListener('input', schedule); current.removeEventListener('zipper-measure', schedule);
        if (addedId) current.removeAttribute('id');
      }
      contentChanges.disconnect(); current = next || null; target.current = current;
      if (current) {
        addedId = !current.id;
        if (addedId) current.id = `scroll-${id}`;
        thumbEl.setAttribute('aria-controls', current.id);
        current.classList.add('zipper-native-scroll');
        current.addEventListener('scroll', measure, { passive: true }); current.addEventListener('input', schedule); current.addEventListener('zipper-measure', schedule);
        // Page mutations include this control; ignore its own attribute updates.
        contentChanges.observe(page ? document.body : current, { childList: true, subtree: true, characterData: true });
        observeChildren();
      }
      measure();
    };
    const discovery = new MutationObserver(bind);
    if (!page) discovery.observe(frame, { childList: true, subtree: true });
    bind(); sync.current = measure;
    window.addEventListener('resize', schedule);
    window.addEventListener('scroll', measure, { passive: true, capture: true });
    // Font loading, images and content resize can change scroll geometry.
    frame.addEventListener('load', schedule, true);
    return () => {
      cancelAnimationFrame(raf); resize.disconnect(); contentChanges.disconnect(); discovery.disconnect();
      window.removeEventListener('resize', schedule); window.removeEventListener('scroll', measure, true);
      frame.removeEventListener('load', schedule, true);
      if (current) { current.classList.remove('zipper-native-scroll'); current.removeEventListener('scroll', measure); current.removeEventListener('input', schedule); current.removeEventListener('zipper-measure', schedule); if (addedId) current.removeAttribute('id'); }
      target.current = null; sync.current = () => {};
    };
  }, [targetRef, selector, page, id, horizontal]);

  function move(coordinate: number, offset: number) {
    const content = target.current;
    if (!content || !rail.current || !thumb.current) return;
    const travel = Math.max(0, (horizontal ? rail.current.clientWidth - thumb.current.offsetWidth : rail.current.clientHeight - thumb.current.offsetHeight));
    const position = Math.max(0, Math.min(travel, coordinate - rail.current.getBoundingClientRect()[horizontal ? 'left' : 'top'] - offset));
    const max = Math.max(0, (horizontal ? content.scrollWidth : content.scrollHeight) - (page ? (horizontal ? window.innerWidth : window.innerHeight) : (horizontal ? content.clientWidth : content.clientHeight)));
    content[horizontal ? 'scrollLeft' : 'scrollTop'] = travel ? position / travel * max : 0;
    sync.current();
  }

  return <div ref={rail} hidden className={`zipper-rail${page ? ' zipper-page' : ''}${horizontal ? ' zipper-horizontal' : ''}`}
    onPointerDown={event => {
      if (event.button !== 0 || drag.current) return;
      event.preventDefault(); event.stopPropagation();
      thumb.current?.focus({ preventScroll: true });
      const rect = thumb.current!.getBoundingClientRect();
      const offset = event.target instanceof Node && thumb.current!.contains(event.target) ? (horizontal ? event.clientX - rect.left : event.clientY - rect.top) : (horizontal ? rect.width : rect.height) / 2;
      drag.current = { id: event.pointerId, offset }; setDragging(true);
      event.currentTarget.setPointerCapture(event.pointerId); move(horizontal ? event.clientX : event.clientY, offset);
    }}
    onPointerMove={event => { if (drag.current?.id === event.pointerId) move(horizontal ? event.clientX : event.clientY, drag.current.offset); }}
    onPointerUp={event => { if (drag.current?.id === event.pointerId) { drag.current = null; setDragging(false); event.currentTarget.releasePointerCapture(event.pointerId); } }}
    onPointerCancel={() => { drag.current = null; setDragging(false); }}
    onLostPointerCapture={() => { drag.current = null; setDragging(false); }}>
    <div ref={thumb} className={`zipper-thumb${dragging ? ' dragging' : ''}`} tabIndex={0}
      role="scrollbar" aria-label={label} aria-orientation={horizontal ? 'horizontal' : 'vertical'} aria-valuemin={0}
      aria-valuemax={0} aria-valuenow={0} onKeyDown={event => {
        const content = target.current; if (!content) return;
        const height = page ? (horizontal ? window.innerWidth : window.innerHeight) : (horizontal ? content.clientWidth : content.clientHeight);
        const value = horizontal ? content.scrollLeft : content.scrollTop;
        const next: Record<string, number> = { [horizontal ? 'ArrowLeft' : 'ArrowUp']: value - 40, [horizontal ? 'ArrowRight' : 'ArrowDown']: value + 40,
          PageUp: value - height * .9, PageDown: value + height * .9, Home: 0, End: horizontal ? content.scrollWidth : content.scrollHeight };
        if (event.key in next) { event.preventDefault(); event.stopPropagation(); content[horizontal ? 'scrollLeft' : 'scrollTop'] = next[event.key]; sync.current(); }
      }}>
      <span className="zipper-grip" aria-hidden="true"><span/><span/><span/></span>
    </div>
  </div>;
}
