// The site's own profiles, shown in the footer. A platform with an empty URL
// is left out, so a link only appears once it is filled in.
export const SOCIAL: { id: string; label: string; url: string }[] = [
  { id: 'facebook', label: 'Facebook', url: '' },
  { id: 'threads', label: 'Threads', url: '' },
  { id: 'x', label: 'X', url: '' },
];

// Share links for a page (plain links: nothing is loaded from these sites
// until a reader clicks, in line with the privacy policy).
export const shareLinks = (url: string, title: string) => {
  const u = encodeURIComponent(url);
  const t = encodeURIComponent(title);
  return [
    { id: 'facebook', label: 'Facebook', href: `https://www.facebook.com/sharer/sharer.php?u=${u}` },
    { id: 'x', label: 'X', href: `https://x.com/intent/post?url=${u}&text=${t}` },
    { id: 'threads', label: 'Threads', href: `https://www.threads.net/intent/post?text=${encodeURIComponent(`${title} ${url}`)}` },
  ];
};
