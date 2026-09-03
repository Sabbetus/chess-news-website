export type Continent =
  | 'europe'
  | 'asia'
  | 'north-america'
  | 'south-america'
  | 'africa'
  | 'oceania'
  | 'global';

export const CONTINENT_META: Record<Continent, { label: string; navLabel: string }> = {
  europe: { label: 'Europe', navLabel: 'Europe' },
  asia: { label: 'Asia', navLabel: 'Asia' },
  'north-america': { label: 'North America', navLabel: 'N. America' },
  'south-america': { label: 'South America', navLabel: 'S. America' },
  africa: { label: 'Africa', navLabel: 'Africa' },
  oceania: { label: 'Oceania', navLabel: 'Oceania' },
  global: { label: 'Global', navLabel: 'Global' },
};

// Nav order -- roughly by how much coverage each region gets, Global last
// since it's a catch-all rather than a place.
export const CONTINENT_ORDER: Continent[] = [
  'europe',
  'asia',
  'north-america',
  'south-america',
  'africa',
  'oceania',
  'global',
];
