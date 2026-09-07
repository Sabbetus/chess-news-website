// Wikimedia thumbnail URLs encode their width directly in the path, e.g.
// https://thumb.wikimedia.org/.../1280px-Foo.jpg -- so a resized URL can be
// built by string-rewriting an already-stored URL, with no re-fetch from
// Commons and no change to the drafting pipeline.
const THUMB_WIDTH_SEGMENT = /\/(\d+)px-/;

// Wikimedia's thumbnail service only serves a fixed set of "standard"
// widths for direct (hotlinked) requests -- anything else returns HTTP 400
// ("Use thumbnail sizes listed on https://w.wiki/GHai"). Confirmed by
// testing: 400/640/900px all 400'd, only widths from this list succeeded.
// Requests that go through MediaWiki's own API (like images.py's
// iiurlwidth) get silently rounded up to one of these, which is why a
// requested 1200 became a working 1280px URL -- but any width WE pick for
// a client-side srcset must come from this same list, or the browser gets
// a broken image.
// https://www.mediawiki.org/wiki/Common_thumbnail_sizes ($wgThumbnailSteps)
const STANDARD_WIDTHS = [20, 40, 60, 120, 250, 330, 500, 960, 1280, 1920, 3840];

function roundToStandardWidth(width: number): number {
  return STANDARD_WIDTHS.find((w) => w >= width) ?? STANDARD_WIDTHS[STANDARD_WIDTHS.length - 1];
}

// images.py normally stores a thumburl (matches THUMB_WIDTH_SEGMENT above),
// but MediaWiki's API sometimes omits it -- observed on a file just 4px
// over the requested width, which fell back to the raw, un-resized
// original (1.17MB for one photo, the single largest item in a PageSpeed
// scan). A raw Commons file URL follows its own predictable convention
// (no "thumb/" segment, no width prefix) that can be converted into a
// proper thumbnail URL the same way. Matched against the URL's pathname
// only (not the full href) -- Wikimedia's own URLs carry a
// "?utm_source=..." query string, and matching against the full string
// with a trailing $ anchor would otherwise swallow that query into the
// captured "filename" group.
const RAW_COMMONS_PATH = /^\/wikipedia\/commons\/([0-9a-f])\/([0-9a-f]{2})\/([^/]+)$/;

// SVGs are vector -- there's no raster width to request, and the file
// itself is already tiny, so leave them alone.
function isSvg(pathname: string): boolean {
  return /\.svg$/i.test(pathname);
}

// Commons image URLs arrive on two interchangeable hosts depending on which
// field the API returned -- measured across the built site, 639 on
// thumb.wikimedia.org and 146 on upload.wikimedia.org. Browsers treat those
// as separate origins, so the split costs a second DNS + TLS handshake and
// means a preconnect hint can only ever cover part of the images.
//
// upload is the normalisation target rather than thumb: it serves both
// thumbnail and raw (un-resized) paths directly, where thumb 301-redirects
// the raw ones -- and six stored URLs are still raw originals.
const CANONICAL_HOST = 'upload.wikimedia.org';
const WIKIMEDIA_HOSTS = new Set(['upload.wikimedia.org', 'thumb.wikimedia.org']);

function canonicalizeHost(url: URL): void {
  if (WIKIMEDIA_HOSTS.has(url.hostname)) url.hostname = CANONICAL_HOST;
}

/** Resize a Commons image URL (thumb or raw) to (at least) the given
 * width, rounded up to the nearest width Wikimedia's thumbnail service
 * actually serves. Returns the URL unchanged if it's not a recognized
 * Commons image URL shape, or an SVG (nothing to resize). */
export function resizeUrl(urlStr: string, width: number): string {
  let url: URL;
  try {
    url = new URL(urlStr);
  } catch {
    return urlStr;
  }
  // SVGs are returned unresized, but still normalised onto the canonical
  // host so they don't reopen the second origin on their own.
  if (isSvg(url.pathname)) {
    canonicalizeHost(url);
    return url.toString();
  }

  const standardWidth = roundToStandardWidth(width);

  const thumbMatch = url.pathname.match(THUMB_WIDTH_SEGMENT);
  if (thumbMatch) {
    url.pathname = url.pathname.replace(THUMB_WIDTH_SEGMENT, `/${standardWidth}px-`);
    canonicalizeHost(url);
    return url.toString();
  }

  const rawMatch = url.pathname.match(RAW_COMMONS_PATH);
  if (rawMatch) {
    const [, h1, h2, filename] = rawMatch;
    url.pathname = `/wikipedia/commons/thumb/${h1}/${h2}/${filename}/${standardWidth}px-${filename}`;
    canonicalizeHost(url);
    return url.toString();
  }

  return urlStr;
}

function isResizableCommonsUrl(urlStr: string): boolean {
  let url: URL;
  try {
    url = new URL(urlStr);
  } catch {
    return false;
  }
  if (isSvg(url.pathname)) return false;
  return THUMB_WIDTH_SEGMENT.test(url.pathname) || RAW_COMMONS_PATH.test(url.pathname);
}

export function buildSrcset(url: string, widths: number[]): string | undefined {
  if (!isResizableCommonsUrl(url)) return undefined;
  // De-dupe: several requested widths can round up to the same standard
  // width (e.g. both 400 and 330-500 land on 500), which would otherwise
  // produce a srcset with repeated "500w" descriptors.
  const standardWidths = [...new Set(widths.map(roundToStandardWidth))];
  return standardWidths.map((w) => `${resizeUrl(url, w)} ${w}w`).join(', ');
}
