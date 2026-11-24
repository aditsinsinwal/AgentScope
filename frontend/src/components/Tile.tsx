import {NOT_REPORTED} from "../lib/format";

export function Tile({label, value, note}: {label: string; value: string; note?: string}) {
  const missing = value === NOT_REPORTED;
  return <article className="tile">
    <p className="tile__label">{label}</p>
    <p className={`tile__value${missing ? " tile__value--missing" : ""}`}>{value}</p>
    {note && <p className="tile__note">{note}</p>}
  </article>;
}
