import { createContext, memo, useContext, useEffect, useRef, useState } from "react";

export const ScrollRowsContext = createContext(null);

export function useScrollRows(total, selection, batchSize, rememberKey) {
  const scope = useContext(ScrollRowsContext);
  const sentinel = useRef(null);
  const cacheKey = scope && rememberKey ? scope.page + "/" + rememberKey : null;
  const remembered = (cacheKey && scope.limits.get(cacheKey)) || batchSize;
  const [batch, setBatch] = useState(() => ({ selection, scope, total, visible: remembered }));
  const reset = batch.selection !== selection || batch.scope !== scope || batch.total !== total;
  let initial = batchSize;
  if (batch.scope !== scope || !batch.total) initial = remembered;
  else if (batch.selection === selection) initial = batch.visible;
  if (reset) setBatch({ selection, scope, total, visible: initial });
  const visible = Math.min(total, reset ? initial : batch.visible);

  useEffect(() => {
    if (cacheKey && visible) scope.limits.set(cacheKey, visible);
  }, [scope, cacheKey, visible]);

  useEffect(() => {
    if (visible >= total || !sentinel.current) return;

    let paintFrame;
    let appendFrame;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      // Let the visible skeleton paint before committing the next group of rows.
      paintFrame = requestAnimationFrame(() => {
        appendFrame = requestAnimationFrame(() => {
          setBatch({ selection, scope, total, visible: visible + batchSize });
        });
      });
    });
    observer.observe(sentinel.current);
    return () => {
      observer.disconnect();
      observer.takeRecords();
      cancelAnimationFrame(paintFrame);
      cancelAnimationFrame(appendFrame);
    };
  }, [total, selection, scope, visible, batchSize]);

  return [visible, sentinel];
}

const RowBatch = memo(function RowBatch({ start, end, render }) {
  return render(start, end);
});

export function RowBatches({ visible, batchSize, render }) {
  return Array.from({ length: Math.ceil(visible / batchSize) }, (_, index) => (
    <RowBatch
      key={index}
      start={index * batchSize}
      end={Math.min(visible, (index + 1) * batchSize)}
      render={render}
    />
  ));
}

export function ScrollRows({ sentinel }) {
  return (
    <div ref={sentinel} className="skeleton-rows scroll-rows" role="status">
      <span className="loading-announcement">Загрузка строк</span>
      {[0, 1].map((row) => (
        <div key={row} className="skeleton-row skeleton-card" aria-hidden="true">
          <span className="skeleton-line" />
          <span className="skeleton-line" />
        </div>
      ))}
    </div>
  );
}
