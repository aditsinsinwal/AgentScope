import {type FormEvent, useState} from "react";
import {getToken, setToken} from "../api/client";

/** API token input. Stored in sessionStorage (cleared when the tab closes), sent as a Bearer header. */
export function TokenField({onChange}: {onChange: () => void}) {
  const [value, setValue] = useState(getToken);
  const [saved, setSaved] = useState(() => getToken() !== "");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setToken(value.trim());
    setSaved(value.trim() !== "");
    onChange();
  };
  return <form className="token" onSubmit={submit}>
    <label htmlFor="api-token">API token</label>
    <input id="api-token" type="password" autoComplete="off" spellCheck={false}
      value={value} placeholder="Bearer token"
      onChange={event => setValue(event.target.value)} />
    <button className="btn btn--small" type="submit">{saved && value ? "Update" : "Set"}</button>
    {saved && <button className="btn btn--small btn--ghost" type="button" onClick={() => {
      setValue("");
      setToken("");
      setSaved(false);
      onChange();
    }}>Clear</button>}
  </form>;
}
