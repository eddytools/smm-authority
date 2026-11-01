import { useState, type ReactNode } from "react";

/** Small, original glyphs on coloured tiles. They hint at the source; they are not the brands' logos. */
const TILE: Record<string, { bg: string; fg: string; glyph: ReactNode; label: string }> = {
  rss: { bg: "#f26522", fg: "#fff", label: "RSS feed", glyph: <><circle cx="6.5" cy="17.5" r="1.8" fill="currentColor" /><path d="M5 11a8 8 0 0 1 8 8M5 5.5A13.5 13.5 0 0 1 18.5 19" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></> },
  reddit: { bg: "#ff4500", fg: "#fff", label: "Reddit", glyph: <text x="12" y="16.5" textAnchor="middle" fontSize="11" fontWeight="700" fill="currentColor">r/</text> },
  google_news: { bg: "#4285f4", fg: "#fff", label: "Google News", glyph: <path d="M6 5h9v14H7a1 1 0 0 1-1-1V5zm9 3h3v9a2 2 0 0 1-2 2M8.5 8.5h4M8.5 11.5h4M8.5 14.5h4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /> },
  linkedin: { bg: "#0a66c2", fg: "#fff", label: "LinkedIn", glyph: <text x="12" y="16.5" textAnchor="middle" fontSize="11" fontWeight="700" fill="currentColor">in</text> },
  x: { bg: "#111", fg: "#fff", label: "X", glyph: <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" /> },
  youtube: { bg: "#e62117", fg: "#fff", label: "YouTube", glyph: <path d="M9.5 8v8l7-4z" fill="currentColor" /> },
  blog: { bg: "#7c3aed", fg: "#fff", label: "Blog", glyph: <path d="M7 17l1-4 7-7 3 3-7 7-4 1zM13 8l3 3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" /> },
  newsletter: { bg: "#0d9488", fg: "#fff", label: "Newsletter", glyph: <path d="M5 8l7 5 7-5M5 7h14v10H5z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" /> },
  facebook: { bg: "#1877f2", fg: "#fff", label: "Facebook", glyph: <text x="12.5" y="18" textAnchor="middle" fontSize="15" fontWeight="700" fill="currentColor">f</text> },
  slack: { bg: "#4a154b", fg: "#fff", label: "Slack", glyph: <text x="12" y="17" textAnchor="middle" fontSize="14" fontWeight="700" fill="currentColor">#</text> },
  discord: { bg: "#5865f2", fg: "#fff", label: "Discord", glyph: <path d="M6 8h12a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-6l-3 2.5V16H6a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" /> },
  instagram: { bg: "#c13584", fg: "#fff", label: "Instagram", glyph: <><rect x="6" y="6" width="12" height="12" rx="3.5" fill="none" stroke="currentColor" strokeWidth="1.6" /><circle cx="12" cy="12" r="2.8" fill="none" stroke="currentColor" strokeWidth="1.6" /></> },
  manual: { bg: "#667085", fg: "#fff", label: "Pasted by hand", glyph: <path d="M7 17l1-4 7-7 3 3-7 7-4 1z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" /> },
  other: { bg: "#667085", fg: "#fff", label: "Other", glyph: <circle cx="12" cy="12" r="3" fill="currentColor" /> },
};

export function SourceIcon({ type, size = 22, title }: { type: string; size?: number; title?: string }) {
  const t = TILE[type] ?? TILE.other;
  return (
    <span className="src-icon" style={{ width: size, height: size, background: t.bg, color: t.fg }} title={title ?? t.label} role="img" aria-label={title ?? t.label}>
      <svg viewBox="0 0 24 24" width={size * 0.8} height={size * 0.8} aria-hidden="true">{t.glyph}</svg>
    </span>
  );
}

const hue = (s: string) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const initials = (name: string) => name.replace(/\(.*?\)/g, "").trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("") || "?";

/** The influencer's picture when they have one; otherwise coloured initials (also used if the picture fails to load). */
export function Avatar({ name, url, platform, size = 40 }: { name: string; url?: string | null; platform?: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  return (
    <span className="avatar" style={{ width: size, height: size }}>
      {url && !broken ? (
        <img src={url} alt="" width={size} height={size} loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} />
      ) : (
        <span className="avatar-initials" style={{ background: `hsl(${hue(name)} 55% 42%)`, fontSize: size * 0.4 }} aria-hidden="true">{initials(name)}</span>
      )}
      {platform && <span className="avatar-badge"><SourceIcon type={platform} size={Math.max(14, size * 0.4)} /></span>}
    </span>
  );
}
