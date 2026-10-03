// Alt text for an article photo, built from its Wikimedia Commons file name
// ("File:Javokhir_Sindarov_chess_player.jpg" -> "Javokhir Sindarov chess
// player"). Commons titles describe what is in the picture; the headline,
// which every image used to get as its alt text, does not.
export function imageAlt(sourceUrl: string | undefined, fallback: string): string {
  if (!sourceUrl) return fallback;
  let name = decodeURIComponent(sourceUrl.split('/').pop() ?? '');
  name = name.replace(/^File:/i, '').replace(/\.[a-z0-9]+$/i, '');
  name = name
    .replace(/[_]+/g, ' ')
    .replace(/\((?:cropped[^)]*|[\d\s]+)\)/gi, ' ') // "(cropped)", "(3)", Flickr ids
    .replace(/\b(?:crop|cropped|PD|MET \d+)\b/g, ' ')
    .replace(/([a-z])(\d{2,4})([a-z]?)\b/gi, (_m, a, d) => (d.length === 4 ? `${a} ${d}` : a)) // "Tata2025" -> "Tata 2025", "Xiong23a" -> "Xiong"
    .replace(/\s+-\s+\d+\s*$/, '') // photoset index "... - 63"
    .replace(/(\D)\d{1,2}\s*$/, '$1') // "JonSpeelman24" -> "JonSpeelman"
    .replace(/([a-z])([A-Z])/g, '$1 $2') // "JonSpeelman" -> "Jon Speelman"
    .replace(/\s+/g, ' ')
    .trim();
  // "2021-Matthias-Bluebaum" -> "Matthias Bluebaum, 2021"
  const lead = name.match(/^(\d{4})[-\s]+(.+)$/);
  if (lead) name = `${lead[2].replace(/-/g, ' ')}, ${lead[1]}`;
  return name.length >= 3 ? name : fallback;
}
