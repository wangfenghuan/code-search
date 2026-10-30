import React, { useEffect, useState } from 'react';
import { FileCode, Loader2, AlertCircle } from 'lucide-react';

export default function SourceViewer({ file, startLine, endLine }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!file) {
      setData(null);
      return;
    }
    let isMounted = true;
    setLoading(true);
    setError(null);

    const s = Math.max(1, (startLine || 1) - 4);
    const e = (endLine || startLine || 1) + 12;

    fetch(`/api/source?file=${encodeURIComponent(file)}&start=${s}&end=${e}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((json) => {
        if (isMounted) {
          if (json.error) setError(json.error);
          else setData(json);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [file, startLine, endLine]);

  if (!file) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.5rem 0.75rem', background: 'rgba(15, 23, 42, 0.9)', borderBottom: '1px solid rgba(51, 65, 85, 0.5)', fontSize: '0.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: '#38bdf8' }}>
          <FileCode size={13} />
          <span style={{ fontWeight: 600, color: '#f8fafc' }}>{file}</span>
          <span style={{ color: '#64748b' }}>Lines {startLine} - {endLine}</span>
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', background: '#090d16', padding: '0.5rem 0' }}>
        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '0.5rem', color: '#94a3b8', fontSize: '0.8rem' }}>
            <Loader2 size={16} className="animate-spin" />
            <span>Loading source preview...</span>
          </div>
        )}

        {error && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '0.5rem', color: '#fb7185', fontSize: '0.8rem' }}>
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        {!loading && !error && data && (
          <div className="code-container">
            {data.lines.map((line, idx) => {
              const currentLineNum = data.start_line + idx;
              const isHighlight = currentLineNum >= startLine && currentLineNum <= endLine;
              return (
                <div
                  key={idx}
                  className="code-line"
                  style={{
                    background: isHighlight ? 'rgba(56, 189, 248, 0.12)' : 'transparent',
                    borderLeft: isHighlight ? '2px solid #38bdf8' : '2px solid transparent',
                  }}
                >
                  <span className="code-line-num" style={{ color: isHighlight ? '#38bdf8' : '#475569', fontWeight: isHighlight ? 600 : 400 }}>
                    {currentLineNum}
                  </span>
                  <span className="code-line-content">{line}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
