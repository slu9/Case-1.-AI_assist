"use client";

import { type BannerContent, type BannerType, CHANNELS, CHANNEL_LABELS, type CampaignView, type PromoComponent, type PromoContent, type TextStyle, contrastRatio } from "@/lib";
import { AlertTriangle, CheckCircle2, ImageOff } from "lucide-react";
import { type CSSProperties, useEffect, useMemo, useState } from "react";

export function briefOf(content: BannerContent): string {
  return [content.title, content.text].filter(Boolean).join(". ").slice(0, 400);
}

/** Изображение от нейросети по тексту креатива. Пока оно рисуется, под ним бежит блик. */
export function CreativeArt({ seed }: { seed: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [seed]);
  const show = seed && !failed;
  return (
    <div className={`art ${show ? "drawing" : ""}`} aria-hidden>
      {show && <img src={`/api/agent/image?brief=${encodeURIComponent(seed)}`} alt="" loading="lazy" onError={() => setFailed(true)} />}
    </div>
  );
}

export function MiniCreative({ banner, fallback }: { banner?: { content: BannerContent }; fallback?: string }) {
  if (!banner) {
    if (fallback === undefined) return <div className={"mini none"}><ImageOff size={18} aria-hidden /></div>;
    return <div className={"mini"}><CreativeArt seed={fallback} /></div>;
  }
  return (
    <div className="mini">
      <CreativeArt seed={briefOf(banner.content)} />
    </div>
  );
}

const WEIGHTS: Record<string, number> = { thin: 200, light: 300, regular: 400, medium: 500, "semi-bold": 600, bold: 700 };

function textCss(style: TextStyle | undefined, fallback: CSSProperties = {}): CSSProperties {
  return {
    ...fallback,
    ...(style?.fontSize && { fontSize: style.fontSize }),
    ...(style?.fontWeight && { fontWeight: WEIGHTS[style.fontWeight] }),
    ...(style?.textColor && { color: style.textColor }),
    lineHeight: 1.22,
  };
}

/** Цвет текста, читаемый на фоне: модель может задать тёмный текст на тёмной кнопке. */
function readable(background: string, text?: string): string {
  if (text && contrastRatio(text, background) >= 3) return text;
  return contrastRatio("#FFFFFF", background) >= contrastRatio("#161D18", background) ? "#FFFFFF" : "#161D18";
}

function maxSize(style: TextStyle | undefined, limit: number): TextStyle | undefined {
  return style?.fontSize && style.fontSize > limit ? { ...style, fontSize: limit } : style;
}

function sized(style: TextStyle | undefined, min: number, max: number): TextStyle {
  return { ...style, fontSize: Math.min(max, Math.max(min, style?.fontSize ?? min)) };
}

const STORY_BASE = "#a9f2ae"; // середина градиента сайта: по нему подбирается цвет текста

/** Адреса на домене .example не открываются, поэтому вместо них рисуется нейтральная заглушка. */
function Picture({ url, seed = "" }: { url?: string; seed?: string }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [url]);
  if (!url || broken || new URL(url, "https://x").hostname.endsWith(".example")) return <CreativeArt seed={seed} />;
  return <img className="preview-img" src={url} alt="" onError={() => setBroken(true)} />;
}

function Story({ content }: { content: BannerContent }) {
  return (
    <div className="story">
      <div className="story-bars" aria-hidden><i /><i /><i /></div>
      <div className="story-image"><Picture url={content.image?.url} seed={briefOf(content)} /></div>
      <div className="story-text">
        {content.title && <div className="story-title" style={{ ...textCss(sized(content.titleStyle, 32, 36)), fontWeight: 700, lineHeight: 1.08, color: readable(STORY_BASE, content.titleStyle?.textColor) }}>{content.title}</div>}
        {content.text && <div className="story-body" style={{ ...textCss(sized(content.textStyle, 19, 20)), color: readable(STORY_BASE, content.textStyle?.textColor) }}>{content.text}</div>}
        {content.buttonName && <div className="creative-button" style={{ background: "#14352c", color: "#fff" }}>{content.buttonName}</div>}
      </div>
    </div>
  );
}

function SmartBanner({ content }: { content: BannerContent }) {
  return (
    <div className="smart">
      <div className="smart-text">
        {content.title && <div style={{ ...textCss(sized(content.titleStyle, 18, 20), { fontWeight: 700 }), color: readable(STORY_BASE, content.titleStyle?.textColor) }}>{content.title}</div>}
        {content.text && <div style={{ ...textCss(sized(content.textStyle, 14, 15)), color: readable(STORY_BASE, content.textStyle?.textColor) }}>{content.text}</div>}
        {content.buttonName && <div className="creative-button" style={{ background: "#14352c", color: "#fff" }}>{content.buttonName}</div>}
      </div>
      <Picture url={content.image?.url} seed={briefOf(content)} />
    </div>
  );
}

function AppHome({ content }: { content: BannerContent }) {
  return (
    <div className="app-home">
      <div className="fake" style={{ height: 96 }} />
      <SmartBanner content={content} />
      <div className="fake" style={{ height: 64 }} />
      <div className="fake" style={{ height: 64 }} />
      <div className="fake" style={{ height: 64 }} />
    </div>
  );
}

/** В format: html разрешён только <b>, поэтому разметка не вставляется как HTML. */
function RichText({ text }: { text: string }) {
  return text.split(/(<b>.*?<\/b>)/g).map((part, index) =>
    part.startsWith("<b>") ? <b key={index}>{part.replace(/<\/?b>/g, "")}</b> : <span key={index}>{part.replace(/<[^>]+>/g, "")}</span>,
  );
}

function PromoItem({ item, background, seed }: { item: PromoComponent; background: string; seed: string }) {
  if (item.role === "text") {
    const css = { ...textCss(maxSize(item.textStyle, 30), { fontSize: 16 }), color: readable(background, item.textStyle?.textColor) };
    return <div style={css}>{item.format === "html" ? <RichText text={item.text} /> : item.text}</div>;
  }
  if (item.role === "image") {
    return <div className="frame" style={{ aspectRatio: item.aspectRatio ?? 2 }}><Picture url={item.url} seed={seed} /></div>;
  }
  const fill = item.style?.backgroundColor ?? "#14352c";
  return (
    <div className="creative-button" style={{ ...textCss(maxSize(item.textStyle, 17)), background: fill, color: readable(fill, item.textStyle?.textColor) }}>
      {item.text}
    </div>
  );
}

export function PromoScreen({ content }: { content: PromoContent }) {
  const { component } = content;
  const background = component.style?.backgroundColor ?? "#FFFFFFFF";
  const seed = component.components.flatMap((item) => item.role === "text" ? [item.text.replace(/<[^>]+>/g, "")] : []).join(". ").slice(0, 400);
  return (
    <div className="promo" style={{ background }}>
      {component.components.map((item, index) => <PromoItem key={index} item={item} background={background} seed={seed} />)}
    </div>
  );
}

function Meter({ label, length, limit }: { label: string; length: number; limit: number }) {
  return (
    <div className={`meter ${length > limit ? "over" : ""}`}>
      <div className="place-row"><span>{label}</span><span className="mono muted">{length} из {limit}</span></div>
      <div className="bar"><i style={{ width: `${Math.min(100, (length / limit) * 100)}%` }} /></div>
    </div>
  );
}

function Contrast({ content }: { content: BannerContent }) {
  const text = content.titleStyle?.textColor;
  const background = content.background?.color;
  if (!text || !background) return null;
  const ratio = contrastRatio(text, background);
  const ok = ratio >= 4.5;
  return (
    <div className={`note ${ok ? "lime" : "amber"}`}>
      {ok ? <CheckCircle2 size={17} aria-hidden /> : <AlertTriangle size={17} aria-hidden />}
      <span>
        Контраст заголовка {ratio.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}:1.{" "}
        {ok ? "Текст читается хорошо." : "Этого мало для уверенного чтения, нужно от 4,5:1."}
      </span>
    </div>
  );
}

export function CreativePreview({ campaign, bannerTypes }: { campaign: CampaignView; bannerTypes: BannerType[] }) {
  const [bannerRef, setBannerRef] = useState<string | null>(null);
  const [channel, setChannel] = useState<string>("iOS");
  const [screen, setScreen] = useState<"banner" | "promo">("banner");
  const [zoom, setZoom] = useState(1);
  const [safe, setSafe] = useState(false);

  const banner = campaign.banners.find((b) => b.ref === bannerRef) ?? campaign.banners[0];
  const type = bannerTypes.find((t) => t.id === banner?.bannerTypeId);
  const creative = useMemo(
    () => campaign.creatives.find((c) => c.bannerRef === banner?.ref && c.channelCode === channel)
      ?? campaign.creatives.find((c) => c.bannerRef === banner?.ref),
    [banner?.ref, campaign.creatives, channel],
  );
  const promo = campaign.contents.find((c) => c.ref === creative?.contentRef) ?? campaign.contents[0];

  if (!banner || !type) {
    return <div className="empty-state"><b>Креативов пока нет</b><span>Ассистент соберёт их после уточнения брифа</span></div>;
  }

  const channelAllowed = type.channels.includes(channel);
  const isStory = type.code === "STORY";
  const canvas = screen === "promo" && promo
    ? <PromoScreen content={promo.content} />
    : isStory ? <Story content={banner.content} /> : <AppHome content={banner.content} />;

  return (
    <div className="stack">
      {campaign.banners.length > 1 && (
        <div className="segmented" role="group" aria-label="Баннер">
          {campaign.banners.map((b) => (
            <button key={b.ref} aria-pressed={b.ref === banner.ref} onClick={() => setBannerRef(b.ref)}>{b.name}</button>
          ))}
        </div>
      )}

      <div className="preview-controls">
        <div className="segmented" role="group" aria-label="Канал">
          {CHANNELS.map((code) => (
            <button key={code} aria-pressed={code === channel} onClick={() => setChannel(code)}>{CHANNEL_LABELS[code]}</button>
          ))}
        </div>
        <div className="segmented" role="group" aria-label="Экран">
          <button aria-pressed={screen === "banner"} onClick={() => setScreen("banner")}>Баннер</button>
          <button aria-pressed={screen === "promo"} onClick={() => setScreen("promo")} disabled={!promo}>Промо-экран</button>
        </div>
      </div>

      {!channelAllowed && (
        <div className="note amber">
          <AlertTriangle size={17} aria-hidden />
          <span>Формат «{type.description}» не показывается на {CHANNEL_LABELS[channel]}. Выберите другой канал или формат.</span>
        </div>
      )}

      <div className="stage">
        <div className="stage-scale" style={{ transform: `scale(${zoom})`, marginBottom: `${(zoom - 1) * 704}px` }}>
          {channel === "WEB" ? (
            <div className="browser">
              <div className="browser-bar" aria-hidden><i /><i /><i /><span>www.example.com</span></div>
              <div className="browser-screen">{canvas}</div>
            </div>
          ) : (
            <div className={`phone ${channel === "ANDROID" ? "android" : ""}`}>
              <div className="phone-screen">
                <div className="phone-notch" aria-hidden />
                {safe && <div className="safe" aria-hidden />}
                <div className="device">{canvas}</div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="preview-controls">
        <div className="segmented" role="group" aria-label="Масштаб">
          {[0.75, 1].map((value) => (
            <button key={value} aria-pressed={zoom === value} onClick={() => setZoom(value)}>{value * 100}%</button>
          ))}
        </div>
        <label className="check small">
          <input type="checkbox" checked={safe} onChange={(e) => setSafe(e.target.checked)} />
          Безопасные зоны
        </label>
      </div>

      <div className="checks">
        <Meter label="Заголовок" length={banner.content.title?.length ?? 0} limit={type.titleMaxLength} />
        <Meter label="Текст" length={banner.content.text?.length ?? 0} limit={type.textMaxLength} />
        <Contrast content={banner.content} />
      </div>
    </div>
  );
}
